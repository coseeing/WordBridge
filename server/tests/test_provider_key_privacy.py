"""The provider API key never reaches a request URL or the log.

The server's own provider keys must not land in the server log: a key in a
logged URL or in logged exception text is a key handed to whoever reads it.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.lib.llm import provider as provider_module

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
