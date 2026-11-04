import json
from pathlib import Path

import pytest

from lib.catalog.document import build_catalog
from lib.catalog.remote import PROVIDER_URL_RULES, filter_provider_urls
from lib.llm import SUPPORTED_PROVIDERS


SERVER_CATALOG = Path(__file__).resolve().parents[1] / "server" / "app" / "setting" / "catalog.json"


def _provider(url):
	return {
		"label": "x",
		"url": url,
		"setting": {},
		"timeout0": 10,
		"timeout_max": 60,
	}


def test_every_provider_url_in_the_server_catalog_is_allowed():
	providers = json.loads(SERVER_CATALOG.read_text(encoding="utf8"))["providers"]

	kept, issues = filter_provider_urls(providers)

	assert kept == providers
	assert issues == ()


@pytest.mark.parametrize("name", sorted(PROVIDER_URL_RULES))
def test_a_foreign_host_is_dropped_for_each_provider(name):
	document = {
		"schema_version": 1,
		"providers": {name: _provider("https://evil.test/v1/x?key=secret")},
		"models": [{"model": "m", "provider": name, "label": "m"}],
	}

	kept, issues = filter_provider_urls(document["providers"])

	assert [(issue.code, issue.location) for issue in issues] == [
		("disallowed_provider_url", f"providers.{name}"),
	]
	detail = issues[0].detail
	assert "evil.test" in detail
	assert "/v1" not in detail
	assert "secret" not in detail

	catalog = build_catalog(dict(document, providers=kept), runnable_providers=SUPPORTED_PROVIDERS)
	assert catalog.get_provider(name) is None
	assert ("unknown_provider", "models[0]") in [(issue.code, issue.location) for issue in catalog.issues]


# (id, provider, url, dropped)
RULES_TABLE = [
	("http-anthropic", "Anthropic", "http://api.anthropic.com/v1/messages", True),
	("ollama-localhost", "Ollama", "http://localhost:11434/v1", False),
	("ollama-v4", "Ollama", "http://127.0.0.1:11434/v1", False),
	("ollama-https", "Ollama", "https://localhost:11434/v1", False),
	("ollama-lan", "Ollama", "http://10.0.0.5:11434/v1", True),
	("openai-port", "OpenAI", "https://api.openai.com:8443/v1", True),
	("openai-explicit-443", "OpenAI", "https://api.openai.com:443/v1", False),
	("userinfo", "OpenAI", "https://user:pw@api.openai.com/v1", True),
	("lookalike", "OpenAI", "https://api.openai.com.evil.test/v1", True),
	("subdomain", "OpenAI", "https://x.api.openai.com/v1", True),
	("upper-host", "OpenAI", "https://API.OPENAI.COM/v1", False),
	("bad-ipv6", "OpenAI", "https://[::1/v1", True),
	("bad-port", "OpenAI", "https://api.openai.com:abc/v1", True),
	("url-int", "OpenAI", 5, True),
	("url-list", "OpenAI", ["https://api.openai.com"], True),
	# urlsplit() silently removes tab/CR/LF and leading C0 controls/spaces,
	# so these would pass the host check while requests rejects the raw URL.
	("tab-inside", "OpenAI", "https://api.openai.com\t/v1", True),
	("tab-in-host", "OpenAI", "https://api.open\tai.com/v1", True),
	("newline", "OpenAI", "https://api.openai.com/v1\n", True),
	("carriage-return", "OpenAI", "https://api.openai.com\r/v1", True),
	("leading-tab", "OpenAI", "\thttps://api.openai.com/v1", True),
	("leading-c0", "OpenAI", "\x01https://api.openai.com/v1", True),
	("leading-space", "OpenAI", " https://api.openai.com/v1", True),
	("trailing-space", "OpenAI", "https://api.openai.com/v1 ", True),
	("ideographic-space", "OpenAI", "https://api.openai.com/v1\u3000", True),
	("escape", "OpenAI", "https://api.openai.com/v1\x1b", True),
	("trailing-dot", "OpenAI", "https://api.openai.com./v1", True),
	("ollama-lookalike", "Ollama", "http://localhost.evil.com:11434/v1", True),
	("ollama-v6", "Ollama", "http://[::1]:11434/v1", True),
	("no-scheme", "OpenAI", "//api.openai.com/v1", True),
	("backslash-userinfo", "OpenAI", "https://evil\\@api.openai.com/v1", True),
	("percent-dot", "OpenAI", "https://api%2eopenai.com/v1", True),
]


@pytest.mark.parametrize("provider, url, dropped", [row[1:] for row in RULES_TABLE], ids=[row[0] for row in RULES_TABLE])
def test_provider_url_rules_table(provider, url, dropped):
	kept, issues = filter_provider_urls({provider: _provider(url)})

	assert (provider in kept) is not dropped
	if dropped:
		assert [(issue.code, issue.location) for issue in issues] == [
			("disallowed_provider_url", f"providers.{provider}"),
		]
		assert "/v1" not in issues[0].detail
	else:
		assert issues == ()


def test_an_unknown_provider_name_is_dropped():
	kept, issues = filter_provider_urls({"Mistral": _provider("https://api.mistral.ai/v1")})

	assert kept == {}
	assert [(issue.code, issue.location) for issue in issues] == [
		("disallowed_provider_url", "providers.Mistral"),
	]


def test_shapes_build_catalog_reports_are_left_alone():
	assert filter_provider_urls(["x"]) == (["x"], ())
	assert filter_provider_urls(None) == (None, ())

	providers = {
		"OpenAI": "not a mapping",
		"Google": {"label": "Google"},
		"DeepSeek": _provider(None),
	}
	kept, issues = filter_provider_urls(providers)

	assert kept == providers
	assert issues == ()


def test_the_input_is_not_mutated():
	providers = {"OpenAI": _provider("https://evil.test/")}

	filter_provider_urls(providers)

	assert "OpenAI" in providers


def test_rules_cover_exactly_the_supported_providers():
	assert set(PROVIDER_URL_RULES) == SUPPORTED_PROVIDERS


def test_the_whole_rules_table_is_pinned():
	# A change to any provider's schemes, hosts or port rule must be a
	# deliberate edit here too: users' API keys are sent to these hosts.
	assert {
		name: (set(rule.schemes), set(rule.hosts), rule.any_port)
		for name, rule in PROVIDER_URL_RULES.items()
	} == {
		"Anthropic": ({"https"}, {"api.anthropic.com"}, False),
		"DeepSeek": ({"https"}, {"api.deepseek.com"}, False),
		"Google": ({"https"}, {"generativelanguage.googleapis.com"}, False),
		"OpenAI": ({"https"}, {"api.openai.com"}, False),
		"OpenRouter": ({"https"}, {"openrouter.ai"}, False),
		"Ollama": ({"http", "https"}, {"localhost", "127.0.0.1"}, True),
	}
