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
