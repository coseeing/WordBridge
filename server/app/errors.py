"""Error responses the add-on can tell apart.

Every error this server raises itself answers
{"detail": <English, for developers>, "code": <fixed code>}, plus "limit"
on the two length errors. The add-on speaks a translated message for each
code. 401s keep their plain {"detail": ...} body, and FastAPI's own
validation 422s keep theirs.

Responses never carry the AI service's own error text: it is written for
people using their own key, may hold account details, and the server has
no translations. It goes to the log instead, with the keys masked.
"""

import logging

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .lib.llm import LLMServiceError

logger = logging.getLogger(__name__)

# LLMServiceError.kind -> code (502).
PROVIDER_CODES = {
	"overloaded": "provider_overloaded",
	"rate_limited": "provider_rate_limited",
	"unreachable": "provider_unreachable",
	"configuration": "provider_configuration",
	"other": "provider_error",
}

_PROVIDER_DETAILS = {
	"overloaded": "The AI service is overloaded.",
	"rate_limited": "The AI service's rate limit or quota was reached.",
	"unreachable": "The AI service could not be reached.",
	"configuration": "The AI service rejected the server's configuration.",
	"other": "The AI service returned an error.",
}

SERVICE_ERROR_DETAIL = "The proofreading service encountered an internal error."


class ApiError(HTTPException):
	"""An HTTPException whose body also carries `code` (and `limit`)."""

	def __init__(self, status_code: int, code: str, detail: str, *, limit: int | None = None):
		super().__init__(status_code=status_code, detail=detail)
		self.code = code
		self.limit = limit


def provider_failure(error: LLMServiceError) -> ApiError:
	"""The 502 for an AI service failure; its text stays out of the body."""
	kind = error.kind if error.kind in PROVIDER_CODES else "other"
	return ApiError(502, PROVIDER_CODES[kind], _PROVIDER_DETAILS[kind])


def service_error() -> ApiError:
	"""The 500 for a server bug or a failed database write."""
	return ApiError(500, "service_error", SERVICE_ERROR_DETAIL)


def masked(text: str, secrets) -> str:
	"""`text` with every non-empty secret replaced by ***."""
	for secret in secrets:
		if secret:
			text = text.replace(secret, "***")
	return text


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
	body = {"detail": exc.detail, "code": exc.code}
	if exc.limit is not None:
		body["limit"] = exc.limit
	return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
	# Starlette's ServerErrorMiddleware calls this for an exception nothing
	# else handled, then re-raises it, so the server logs the traceback.
	error = service_error()
	return JSONResponse(status_code=error.status_code, content={"detail": error.detail, "code": error.code})
