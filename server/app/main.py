import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastcrud import FastCRUD, crud_router
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.exc import NoResultFound

from .dependencies import get_db
from .dependenciesA import get_session

from .models.models import Interaction as InteractionModel
from .models.schemas import Interaction as InteractionSchema
from .user.models import User as UserModel
from .user.routers import router as userRouter, get_auth_user
from .user.schemas import User as UserSchema
from .user.auth import get_optional_user

from dotenv import load_dotenv
load_dotenv()

from .correction_config import load_correction_settings, resolve_model
from .lib.application.task_runner import run_typo_correction
from .lib.decimalUtils import decimal_to_str_0
from .lib.tasks.typo.utils import strings_diff

logger = logging.getLogger(__name__)

app = FastAPI()
app.include_router(userRouter)

# Process-wide deployment settings for the /proofreader correction workflow
# (bundled catalog + task config). Validates the deployment default model at
# import time -- a broken deployment fails loudly at startup rather than
# silently misbehaving per-request.
CORRECTION_SETTINGS = load_correction_settings()

GUEST_TEXT_LIMIT = 128
GUEST_IP_QUOTA = Decimal("0.06")
GUEST_GLOBAL_QUOTA = Decimal("0.3")
QUOTA_WINDOW = timedelta(hours=24)

# Interaction.ip_address is String(45). This does not change get_client_ip()'s
# X-Forwarded-For trust model (keeping that as-is for this phase is
# plan-mandated) -- it only guards against a client-controlled value too long
# to store. Without this, an oversized value reaches the INSERT only *after*
# the paid provider call has already run; the INSERT fails under MySQL strict
# mode, the transaction rolls back, and the cost of a call that already
# happened is never recorded against any guest quota. Normalizing before the
# quota check and before the provider call closes that hole.
IP_ADDRESS_MAX_LENGTH = 45
_INVALID_IP_PLACEHOLDER = "invalid"

_QUOTA_EXCEEDED_DETAIL = (
	"Rate limit reached for requests or you exceeded your current quota. "
	"Please reduce the frequency of sending requests or check your account balance."
)


class ProofreaderRequest(BaseModel):
	request: str = Field(min_length=1)
	corrector_config_id: str = Field(min_length=1)
	language: Literal["zh_traditional", "zh_simplified"]
	typo_correction_mode: str
	customized_words: List[str] = Field(default_factory=list)

	@field_validator("typo_correction_mode")
	@classmethod
	def _validate_mode(cls, value: str) -> str:
		if value not in CORRECTION_SETTINGS.template_name:
			raise ValueError(f"unsupported typo_correction_mode: {value!r}")
		return value


def get_client_ip(request: Request) -> str:
	x_forwarded_for = request.headers.get("X-Forwarded-For")
	if x_forwarded_for:
		ip = x_forwarded_for.split(",")[0].strip()
	else:
		ip = request.client.host
	return ip


def _storable_ip(ip: Optional[str]) -> str:
	"""Normalize a client IP value so it always fits ip_address (String(45)).

	Applied to whatever get_client_ip() returned, before it is used for a
	quota lookup or stored on an Interaction row -- see the comment on
	IP_ADDRESS_MAX_LENGTH above.
	"""
	if not ip or len(ip) > IP_ADDRESS_MAX_LENGTH:
		return _INVALID_IP_PLACEHOLDER
	return ip


def _sum_cost(db: Session, *, since: datetime, user_id_is_none: bool, user_id=None, ip_address=None) -> Decimal:
	query = db.query(func.sum(InteractionModel.cost)).filter(InteractionModel.request_time > since)
	if user_id_is_none:
		query = query.filter(InteractionModel.user_id.is_(None))
	elif user_id is not None:
		query = query.filter(InteractionModel.user_id == user_id)
	if ip_address is not None:
		query = query.filter(InteractionModel.ip_address == ip_address)
	total = query.scalar()
	return Decimal(str(total)) if total is not None else Decimal("0")


def _enforce_quota(db: Session, *, user: Optional[UserModel], client_ip: str, text: str) -> None:
	if user is None and len(text) > GUEST_TEXT_LIMIT:
		raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=_QUOTA_EXCEEDED_DETAIL)

	since = datetime.now(timezone.utc) - QUOTA_WINDOW

	if user is not None:
		if user.is_superuser:
			return
		user_cost = _sum_cost(db, since=since, user_id_is_none=False, user_id=user.id)
		if user_cost >= Decimal(str(user.quota)):
			raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=_QUOTA_EXCEEDED_DETAIL)
		return

	ip_cost = _sum_cost(db, since=since, user_id_is_none=True, ip_address=client_ip)
	global_cost = _sum_cost(db, since=since, user_id_is_none=True)
	if ip_cost >= GUEST_IP_QUOTA or global_cost >= GUEST_GLOBAL_QUOTA:
		raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=_QUOTA_EXCEEDED_DETAIL)


@app.post("/proofreader")
def proofreader(
	http_request: Request,
	data: ProofreaderRequest,
	user: Optional[UserModel] = Depends(get_optional_user),
	db: Session = Depends(get_db),
):
	client_ip = _storable_ip(get_client_ip(http_request))
	text = data.request

	_enforce_quota(db, user=user, client_ip=client_ip, text=text)

	try:
		model_entry = resolve_model(CORRECTION_SETTINGS, data.corrector_config_id)
	except LookupError:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="The requested model is unavailable.",
		)

	provider_entry = CORRECTION_SETTINGS.catalog.get_provider(model_entry.provider)
	if provider_entry is None:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="The requested model is unavailable.",
		)

	api_key = os.environ.get(f"{model_entry.provider.upper()}_API_KEY")
	if not api_key:
		logger.error("Missing API key for provider %s", model_entry.provider)
		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail="The proofreading service is temporarily unavailable.",
		)
	credential = {"api_key": api_key}

	template_name = CORRECTION_SETTINGS.template_name[data.typo_correction_mode]
	optional_guidance_enable = CORRECTION_SETTINGS.optional_guidance_enable

	request_time = datetime.now(timezone.utc)
	try:
		result = run_typo_correction(
			request=text,
			batch_mode=True,
			provider_name=model_entry.provider,
			model_name=model_entry.model,
			credential=credential,
			provider_entry=provider_entry,
			price_entry=model_entry.price_entry(),
			language=data.language,
			template_name=template_name,
			corrector_mode=data.typo_correction_mode,
			optional_guidance_enable=optional_guidance_enable,
			customized_words=data.customized_words,
			retries=2,
			backoff=1,
		)
	except Exception:
		# Never surface exception details (may include the credential) to the
		# client or the log.
		logger.exception("proofreader execution failed for provider %s", model_entry.provider)
		raise HTTPException(
			status_code=status.HTTP_502_BAD_GATEWAY,
			detail="The proofreading service failed to process the request.",
		)
	response_time = datetime.now(timezone.utc)

	response_text = result.corrected_text
	cost = result.cost
	diff = strings_diff(text, response_text)

	interaction = InteractionModel(
		request_time=request_time,
		response_time=response_time,
		request_content=text,
		response_content=response_text,
		ip_address=client_ip,
		cost=cost,
		model=model_entry.corrector_config_id,
		version="20260425",
		user=user,
	)
	interaction.category = "1"

	try:
		db.add(interaction)
		db.commit()
		db.refresh(interaction)
	except Exception:
		db.rollback()
		logger.exception("failed to persist proofreader interaction")
		raise HTTPException(
			status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
			detail="Failed to record the correction result.",
		)

	return {
		"request": text,
		"response": response_text,
		"diff": diff,
		"interaction_id": interaction.id,
		"cost": decimal_to_str_0(cost),
	}


@app.post("/feedback")
def feedback(
	data: dict,
	user = Depends(get_auth_user),
	db: Session = Depends(get_db),
):
	review_content = data["review_content"]
	interaction_id = data["interaction_id"]
	try:
		instance = db.query(InteractionModel).filter(InteractionModel.id==interaction_id).one()
	except NoResultFound:
		raise HTTPException(status_code=404, detail="interaction not found")

		request_time = response_time = datetime.now(timezone.utc)
		interaction = InteractionModel(
			request_time=request_time,
			response_time=response_time,
			request_content=request,
			response_content=response,
			ip_address="0.0.0.0",
			usage=usages,
			model="",
			version="20240617",
			user=user,
		)

	instance.review_content = review_content
	instance.review_user_id = user.id

	db.commit()
	return {}


user_crud = FastCRUD(UserModel)
user_router = crud_router(
	session=get_session,
	model=UserModel,
	crud=user_crud,
	create_schema=UserSchema,
	update_schema=UserSchema,
	path="/users",
	tags=["Users"],
)

app.include_router(
	user_router,
	dependencies=[Depends(get_auth_user)],
)

interaction_crud = FastCRUD(InteractionModel)
interaction_router = crud_router(
	session=get_session,
	model=InteractionModel,
	crud=interaction_crud,
	create_schema=InteractionSchema,
	update_schema=InteractionSchema,
	path="/interactions",
	tags=["Interactions"],
)

app.include_router(
	interaction_router,
	dependencies=[Depends(get_auth_user)],
)
