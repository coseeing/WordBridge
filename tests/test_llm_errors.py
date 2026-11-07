"""Every failure the LLM layer reports to the user is an LLMServiceError.

Callers show str(error) to the user, so the class changes nothing they see;
it lets a caller tell a provider or response failure apart from a bug.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ADDON_PATH = Path(__file__).parents[1] / "addon" / "globalPlugins" / "WordBridge"
sys.path.insert(0, str(ADDON_PATH))

from lib.llm import LLMServiceError
from lib.llm import executor as executor_module
from lib.llm import provider as provider_module

OPENAI_URL = "https://api.openai.com/v1/responses"


def _provider():
	entry = SimpleNamespace(url=OPENAI_URL, setting={}, timeout0=1, timeout_max=1)
	provider = provider_module.OpenAIProvider({"api_key": "key"}, provider_entry=entry)
	provider.retries = 1
	provider.backoff = 0
	return provider


def test_it_is_an_exception():
	# Callers catch Exception; they keep catching it.
	assert issubclass(LLMServiceError, Exception)


@pytest.mark.parametrize(
	"status, text, message",
	[
		(401, "", "Authentication error."),
		(403, "", "Country, region, or territory not supported."),
		(404, "", "Service does not exist."),
		(429, "", "Rate limit reached for requests"),
		(503, "", "The server is currently overloaded"),
		(500, '{"error": {"message": "boom"}}', "An error occurred, status code = 500, boom"),
	],
	ids=["401", "403", "404", "429", "503", "other"],
)
def test_an_http_error_is_an_llm_service_error(status, text, message):
	response = SimpleNamespace(status_code=status, text=text)

	with pytest.raises(LLMServiceError, match=message):
		_provider().handle_errors(response)


def test_an_unreachable_provider_on_send_is_an_llm_service_error():
	with (
		patch.object(provider_module.requests, "post", side_effect=OSError("down")),
		patch.object(provider_module, "log", MagicMock()),
		patch.object(provider_module.time, "sleep"),
		pytest.raises(LLMServiceError, match=r"HTTP request error \(OSError\)"),
	):
		_provider().send({})


def test_an_unreachable_provider_on_try_connection_is_an_llm_service_error():
	with (
		patch.object(provider_module.requests, "get", side_effect=OSError("down")),
		patch.object(provider_module, "log", MagicMock()),
		pytest.raises(LLMServiceError, match=r"HTTP request error \(OSError\)"),
	):
		_provider().try_connection(try_count=1)


class _Policy:
	def has_target_language(self, text):
		return True


class _Strategy:
	def compose(self, **kwargs):
		return None


class _Adapter:
	def format_request(self, **kwargs):
		return {}

	def parse_response(self, response_json):
		raise KeyError("output")


class _Provider:
	def __init__(self):
		self.setting = {}

	def send(self, payload, model_name=None):
		return {"unexpected": True}


def test_an_unexpected_response_shape_is_an_llm_service_error():
	adapter = _Adapter()
	adapter.model_name = "m"
	llm_executor = executor_module.LLMExecutor(_Provider(), adapter)

	with (
		patch.object(executor_module, "log", MagicMock()),
		pytest.raises(LLMServiceError, match="Parsing error. Unexpected server response."),
	):
		llm_executor.execute("原文", _Strategy(), _Policy())


# --- kind: what kind of failure, for the Coseeing server's error codes -------


@pytest.mark.parametrize(
	"status, text, kind, message",
	[
		(401, "", "configuration", "Authentication error."),
		(403, "", "configuration", "Country, region, or territory not supported."),
		(404, "", "configuration", "Service does not exist."),
		(429, "", "rate_limited", "Rate limit reached for requests"),
		(503, "", "overloaded", "The server is currently overloaded"),
		(
			529,
			'{"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}',
			"overloaded",
			"An error occurred, status code = 529, Overloaded",
		),
		(500, '{"error": {"message": "boom"}}', "other", "An error occurred, status code = 500, boom"),
	],
	ids=["401", "403", "404", "429", "503", "529", "other"],
)
def test_an_http_error_has_its_kind(status, text, kind, message):
	response = SimpleNamespace(status_code=status, text=text, reason="Reason")

	with pytest.raises(LLMServiceError) as raised:
		_provider().handle_errors(response)

	assert raised.value.kind == kind
	assert str(raised.value).startswith(message)


@pytest.mark.parametrize(
	"body",
	[
		"<html>bad gateway</html>",
		"{}",
		'{"error": {}}',
		'{"error": "x"}',
		'{"error": {"message": 5}}',
		"[1]",
		"",
	],
	ids=["html", "empty-object", "no-message", "error-string", "message-not-text", "list", "empty"],
)
@pytest.mark.parametrize("reason", ["Bad Gateway", None], ids=["reason", "no-reason"])
def test_other_status_bodies_never_crash(body, reason):
	response = SimpleNamespace(status_code=502, text=body)
	if reason is not None:
		response.reason = reason

	with pytest.raises(LLMServiceError) as raised:
		_provider().handle_errors(response)

	assert raised.value.kind == "other"
	assert str(raised.value) == f"An error occurred, status code = 502, {reason or ''}"
	for fragment in ("html", '"error"', "[1]", "{", "x"):
		assert fragment not in str(raised.value)


def test_unreachable_errors_have_kind_unreachable():
	with (
		patch.object(provider_module.requests, "post", side_effect=OSError("down")),
		patch.object(provider_module, "log", MagicMock()),
		patch.object(provider_module.time, "sleep"),
		pytest.raises(LLMServiceError) as on_send,
	):
		_provider().send({})
	with (
		patch.object(provider_module.requests, "get", side_effect=OSError("down")),
		patch.object(provider_module, "log", MagicMock()),
		pytest.raises(LLMServiceError) as on_try,
	):
		_provider().try_connection(try_count=1)

	assert on_send.value.kind == on_try.value.kind == "unreachable"


def test_an_unexpected_response_shape_has_kind_other():
	adapter = _Adapter()
	adapter.model_name = "m"
	llm_executor = executor_module.LLMExecutor(_Provider(), adapter)

	with patch.object(executor_module, "log", MagicMock()), pytest.raises(LLMServiceError) as raised:
		llm_executor.execute("原文", _Strategy(), _Policy())

	assert raised.value.kind == "other"


def test_the_kind_defaults_to_other_and_must_be_known():
	assert LLMServiceError("x").kind == "other"
	assert str(LLMServiceError("x", kind="overloaded")) == "x"
	with pytest.raises(ValueError, match="made_up"):
		LLMServiceError("x", kind="made_up")
