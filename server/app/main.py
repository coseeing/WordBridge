import json
import logging
import traceback
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastcrud import FastCRUD, crud_router
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from .client_ip import CLOUDFLARE_RANGES_PATH, load_cloudflare_networks, select_client_ip
from .correction_config import (
	SETTING_DIR,
	load_addon_version,
	load_correction_settings,
	resolve_model,
	template_stem,
)
from .dependencies import get_async_session, get_db
from .errors import (
	ApiError,
	api_error_handler,
	masked,
	provider_failure,
	service_error,
	unexpected_error_handler,
)
from .lib.application.task_runner import run_typo_correction
from .lib.decimalUtils import decimal_to_str_0
from .lib.llm import LLMServiceError
from .lib.tasks.typo.utils import strings_diff
from .models.models import Interaction as InteractionModel
from .models.schemas import Interaction as InteractionSchema
from .settings import SETTINGS
from .user.auth import get_optional_user, require_superuser
from .user.models import User as UserModel
from .user.schemas import User as UserSchema

logger = logging.getLogger(__name__)

app = FastAPI()
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(Exception, unexpected_error_handler)

# Process-wide deployment settings for the /proofreader correction workflow
# (bundled catalog + task config + provider API keys). Validates at import
# time the deployment default model and that every provider a served model
# uses has its API key set -- a broken deployment fails loudly at startup
# rather than silently misbehaving per-request.
CORRECTION_SETTINGS = load_correction_settings(SETTINGS)


def load_catalog_bytes(path) -> bytes:
	"""The payload GET / serves: the catalog file without its providers.

	Checked once: the file must be a JSON object with schema_version 1.
	Raises ValueError for anything else, the same fail-loud stance as
	load_correction_settings(): a broken deployment stops at startup instead
	of serving a payload every add-on rejects.

	The add-on bundles its own provider entries and rejects a payload that
	carries them; the file keeps them for this server's own correction
	calls. Every other key is served, in file order, as UTF-8 JSON text
	indented like the file.
	"""
	content = path.read_bytes()
	try:
		document = json.loads(content)
	except ValueError as error:
		raise ValueError(f"{path.name} is not valid JSON") from error
	if not isinstance(document, dict) or document.get("schema_version") != 1:
		raise ValueError(f"{path.name} must be a JSON object with schema_version 1")
	served = {key: value for key, value in document.items() if key != "providers"}
	return (json.dumps(served, ensure_ascii=False, indent="\t") + "\n").encode("utf8")


# The file only changes with a deployment, so it is read once.
CATALOG_BYTES = load_catalog_bytes(SETTING_DIR / "catalog.json")

# Recorded with every correction; a missing or blank file stops startup.
ADDON_VERSION = load_addon_version()

# Bundled with the image; a missing file or a bad line stops startup.
CLOUDFLARE_NETWORKS = load_cloudflare_networks(CLOUDFLARE_RANGES_PATH)

# Applies to every caller (guest, authenticated, superuser). Chosen comfortably
# below both limits a request that exceeds it can otherwise blow past only
# *after* the paid provider call already ran: create_single_char_mapping's
# diffing raises ValueError around ~20000 tokens (~10k CJK characters), and
# request_content/response_content are MySQL TEXT columns (65,535 bytes,
# ~21.8k CJK characters). It is checked first, before the guest text limit
# (GUEST_TEXT_LIMIT, from app/settings.py, guests only), the quota check and
# the provider call, and answers 413 text_too_long with the limit.
REQUEST_TEXT_MAX_LENGTH = 8000

# Interaction.ip_address is String(45). get_client_ip() takes the address
# from headers (app/client_ip.py explains which and why), and the TCP peer
# can also be something other than an address, so the value is length-checked
# before use. Without this, an oversized value reaches the INSERT only *after*
# the paid provider call has already run; the INSERT fails under MySQL strict
# mode, the transaction rolls back, and the cost of a call that already
# happened is never recorded against any guest quota. Normalizing before the
# quota check and before the provider call closes that hole.
IP_ADDRESS_MAX_LENGTH = 45
_INVALID_IP_PLACEHOLDER = "invalid"

_MODEL_UNAVAILABLE_DETAIL = "The requested model is unavailable."


class ProofreaderRequest(BaseModel):
	# The upper limit is checked in proofreader(), to answer 413 with a code.
	request: str = Field(min_length=1)
	corrector_config_id: str = Field(min_length=1)
	language: Literal["zh_traditional", "zh_simplified"]
	typo_correction_mode: str
	customized_words: list[str] = Field(default_factory=list)

	@field_validator("typo_correction_mode")
	@classmethod
	def _validate_mode(cls, value: str) -> str:
		if value not in CORRECTION_SETTINGS.template_name:
			raise ValueError(f"unsupported typo_correction_mode: {value!r}")
		return value


def get_client_ip(request: Request) -> str | None:
	"""The guest's address under CLIENT_IP_SOURCE (see app/client_ip.py)."""
	return select_client_ip(
		forwarded_for=request.headers.getlist("x-forwarded-for"),
		cf_connecting_ip=request.headers.get("cf-connecting-ip"),
		peer_host=request.client.host if request.client else None,
		source=SETTINGS.client_ip_source,
		cloudflare_networks=CLOUDFLARE_NETWORKS,
	)


def _storable_ip(ip: str | None) -> str:
	"""Normalize a client IP value so it always fits ip_address (String(45)).

	Applied to whatever get_client_ip() returned, before it is used for a
	quota lookup or stored on an Interaction row -- see the comment on
	IP_ADDRESS_MAX_LENGTH above.
	"""
	if not ip or len(ip) > IP_ADDRESS_MAX_LENGTH:
		return _INVALID_IP_PLACEHOLDER
	return ip


def _sum_cost(
	db: Session,
	*,
	since: datetime,
	user_id_is_none: bool,
	user_id=None,
	ip_address=None,
) -> Decimal:
	query = db.query(func.sum(InteractionModel.cost)).filter(InteractionModel.request_time > since)
	if user_id_is_none:
		query = query.filter(InteractionModel.user_id.is_(None))
	elif user_id is not None:
		query = query.filter(InteractionModel.user_id == user_id)
	if ip_address is not None:
		query = query.filter(InteractionModel.ip_address == ip_address)
	total = query.scalar()
	return Decimal(str(total)) if total is not None else Decimal(0)


def _enforce_length(*, user: UserModel | None, text: str) -> None:
	if len(text) > REQUEST_TEXT_MAX_LENGTH:
		raise ApiError(
			status.HTTP_413_CONTENT_TOO_LARGE,
			"text_too_long",
			f"The text is longer than {REQUEST_TEXT_MAX_LENGTH} characters.",
			limit=REQUEST_TEXT_MAX_LENGTH,
		)
	if user is None and len(text) > SETTINGS.guest_text_limit:
		raise ApiError(
			status.HTTP_413_CONTENT_TOO_LARGE,
			"guest_text_too_long",
			f"Guests can send up to {SETTINGS.guest_text_limit} characters.",
			limit=SETTINGS.guest_text_limit,
		)


def _enforce_quota(db: Session, *, user: UserModel | None, client_ip: str) -> None:

	since = datetime.now(timezone.utc) - SETTINGS.quota_window

	if user is not None:
		if user.is_superuser:
			return
		user_cost = _sum_cost(db, since=since, user_id_is_none=False, user_id=user.id)
		if user_cost >= Decimal(str(user.quota)):
			raise ApiError(
				status.HTTP_429_TOO_MANY_REQUESTS,
				"user_quota_exceeded",
				"This account's quota has been used up.",
			)
		return

	ip_cost = _sum_cost(db, since=since, user_id_is_none=True, ip_address=client_ip)
	global_cost = _sum_cost(db, since=since, user_id_is_none=True)
	if ip_cost >= SETTINGS.guest_ip_quota or global_cost >= SETTINGS.guest_global_quota:
		raise ApiError(
			status.HTTP_429_TOO_MANY_REQUESTS,
			"guest_quota_exceeded",
			"The guest quota has been used up.",
		)


@app.get("/")
def catalog():
	"""The model catalog the add-on downloads (no provider entries; the add-on
	bundles them). Public data: no authentication."""
	return Response(
		content=CATALOG_BYTES,
		media_type="application/json",
		headers={"Cache-Control": "no-cache"},
	)


@app.post("/proofreader")
def proofreader(
	http_request: Request,
	data: ProofreaderRequest,
	user: UserModel | None = Depends(get_optional_user),
	db: Session = Depends(get_db),
):
	client_ip = _storable_ip(get_client_ip(http_request))
	text = data.request

	_enforce_length(user=user, text=text)
	_enforce_quota(db, user=user, client_ip=client_ip)

	try:
		model_entry = resolve_model(CORRECTION_SETTINGS, data.corrector_config_id)
	except LookupError:
		raise ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, "model_unavailable", _MODEL_UNAVAILABLE_DETAIL)

	provider_entry = CORRECTION_SETTINGS.catalog.get_provider(model_entry.provider)
	if provider_entry is None:
		raise ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, "model_unavailable", _MODEL_UNAVAILABLE_DETAIL)

	# Read and checked at startup (load_correction_settings), so every
	# servable model's provider has one.
	credential = {"api_key": CORRECTION_SETTINGS.api_keys[model_entry.provider]}

	template_name = CORRECTION_SETTINGS.template_name[data.typo_correction_mode]
	optional_guidance_enable = CORRECTION_SETTINGS.optional_guidance_enable

	# End the quota check's read-only transaction so its pooled connection is
	# free while the AI service answers (seconds to tens of seconds). The
	# write below takes a connection again; `user` belongs to this session,
	# expires here and reloads on that write.
	try:
		db.commit()
	except Exception:
		db.rollback()
		logger.exception("failed to end the quota check transaction")
		raise service_error()

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
	except LLMServiceError as error:
		# Details go to the log, never to the client, and never with a key:
		# the AI service's own text can echo the key it was sent.
		logger.warning(
			"AI service %s failed (%s): %s",
			model_entry.provider,
			error.kind,
			masked(str(error), CORRECTION_SETTINGS.api_keys.values()),
		)
		raise provider_failure(error)
	except Exception:  # noqa: BLE001 -- logged with its traceback below, then a 500
		# A bug, not an AI service failure: the full traceback goes to the log,
		# with the keys masked in case an exception's text carries one, and
		# never to the client.
		logger.error(
			"proofreader execution failed for provider %s:\n%s",
			model_entry.provider,
			masked(traceback.format_exc(), CORRECTION_SETTINGS.api_keys.values()),
		)
		raise service_error()
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
		version=ADDON_VERSION,
		template=template_stem(template_name),
		user=user,
	)

	try:
		db.add(interaction)
		db.commit()
		db.refresh(interaction)
	except Exception:
		db.rollback()
		logger.exception("failed to persist proofreader interaction")
		raise service_error()

	return {
		"request": text,
		"response": response_text,
		"diff": diff,
		"interaction_id": interaction.id,
		"cost": decimal_to_str_0(cost),
	}


class FeedbackRequest(BaseModel):
	interaction_id: int
	review_content: str


@app.post("/feedback")
def feedback(
	data: FeedbackRequest,
	user: UserModel | None = Depends(get_optional_user),
	db: Session = Depends(get_db),
):
	try:
		instance = db.query(InteractionModel).filter(InteractionModel.id == data.interaction_id).one()
	except NoResultFound:
		raise HTTPException(status_code=404, detail="interaction not found")

	instance.review_content = data.review_content
	instance.review_user_id = user.id if user else None

	db.commit()
	return {}


user_crud = FastCRUD(UserModel)
user_router = crud_router(
	session=get_async_session,
	model=UserModel,
	crud=user_crud,
	create_schema=UserSchema,
	update_schema=UserSchema,
	path="/users",
	tags=["Users"],
)

app.include_router(
	user_router,
	dependencies=[Depends(require_superuser)],
)

interaction_crud = FastCRUD(InteractionModel)
interaction_router = crud_router(
	session=get_async_session,
	model=InteractionModel,
	crud=interaction_crud,
	create_schema=InteractionSchema,
	update_schema=InteractionSchema,
	path="/interactions",
	tags=["Interactions"],
)

app.include_router(
	interaction_router,
	dependencies=[Depends(require_superuser)],
)
