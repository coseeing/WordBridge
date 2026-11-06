"""The provider API key never reaches a request URL or the log.

Users paste their NVDA log into bug reports, so a key in a logged URL or in
logged exception text is a key handed to whoever reads the report.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ADDON_PATH = Path(__file__).parents[1] / "addon" / "globalPlugins" / "WordBridge"
sys.path.insert(0, str(ADDON_PATH))

from lib.llm import provider as provider_module

SECRET = "SECRET-key-1234"
GOOGLE_URL = "https://generativelanguage.googleapis.com/v1beta"


def _entry(url=GOOGLE_URL):
	return SimpleNamespace(url=url, setting={}, timeout0=1, timeout_max=1)


def test_google_request_url_carries_no_key():
	provider = provider_module.GoogleProvider({"api_key": SECRET}, provider_entry=_entry())

	url = provider.get_api_url(model_name="gemini-3.8-flash")

	assert url == f"{GOOGLE_URL}/models/gemini-3.8-flash:generateContent"
	assert "key=" not in url
	assert SECRET not in url


def test_google_key_is_sent_in_the_api_key_header():
	provider = provider_module.GoogleProvider({"api_key": SECRET}, provider_entry=_entry())

	headers = provider.get_headers()

	assert headers["x-goog-api-key"] == SECRET
	assert headers["Content-Type"] == "application/json"
	assert "Authorization" not in headers


def test_google_send_posts_the_key_in_the_header_only():
	provider = provider_module.GoogleProvider({"api_key": SECRET}, provider_entry=_entry())
	provider.retries = 1
	response = MagicMock(status_code=200)
	response.json.return_value = {"ok": True}

	with patch.object(provider_module.requests, "post", return_value=response) as post:
		provider.send({"contents": []}, model_name="gemini-3.8-flash")

	(url,), kwargs = post.call_args
	assert SECRET not in url
	assert kwargs["headers"]["x-goog-api-key"] == SECRET


def _connection_error():
	# What requests raises when the host is unreachable: str() carries the
	# full request URL, query string included.
	error_type = type("ConnectionError", (Exception,), {})
	return error_type(
		"HTTPSConnectionPool(host='generativelanguage.googleapis.com', port=443): "
		f"Max retries exceeded with url: /v1beta/models/gemini:generateContent?key={SECRET} "
		'(Caused by NameResolutionError("Failed to resolve"))',
	)


def _logged_text(log_mock):
	return "\n".join(repr(c) for c in log_mock.mock_calls)


@pytest.mark.parametrize("provider_name", ["Google", "OpenAI", "Anthropic"])
def test_send_failure_logs_the_error_type_but_never_its_text(provider_name):
	provider = provider_module.get_provider(
		provider_name,
		{"api_key": SECRET},
		retries=2,
		provider_entry=_entry(),
	)
	log = MagicMock()

	with (
		patch.object(provider_module.requests, "post", side_effect=_connection_error()),
		patch.object(provider_module.time, "sleep"),
		patch.object(provider_module, "log", log),
		pytest.raises(Exception) as raised,
	):
		provider.send({}, model_name="gemini-3.8-flash")

	logged = _logged_text(log)
	assert log.error.call_count == 2
	assert SECRET not in logged
	assert "key=" not in logged
	assert "ConnectionError" in logged
	assert provider.name in logged
	assert SECRET not in str(raised.value)


def test_try_connection_failure_logs_the_error_type_but_never_its_text():
	provider = provider_module.GoogleProvider({"api_key": SECRET}, provider_entry=_entry())
	log = MagicMock()

	with (
		patch.object(provider_module.requests, "get", side_effect=_connection_error()),
		patch.object(provider_module, "log", log),
		pytest.raises(Exception) as raised,
	):
		provider.try_connection(try_count=2)

	logged = _logged_text(log)
	assert log.error.call_count == 2
	assert SECRET not in logged
	assert "key=" not in logged
	assert "ConnectionError" in logged
	assert provider.name in logged
	assert SECRET not in str(raised.value)
