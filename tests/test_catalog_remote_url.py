import pytest

from lib.catalog.remote import DEFAULT_CATALOG_URL, UrlCheck, redact_url, validate_catalog_url


DEFAULT_KEY = "https://wordbridge.coseeing.org/"
MAX_LENGTH_URL = "https://h.test/" + "a" * 2033

# (id, text, key, error). url is always the stripped text.
TABLE = [
	("empty", "", "", None),
	("blank", "   ", "", None),
	("default", DEFAULT_CATALOG_URL, DEFAULT_KEY, None),
	("padded", "  https://wordbridge.coseeing.org/  ", DEFAULT_KEY, None),
	("ideographic-space-padded", "　https://wordbridge.coseeing.org　", DEFAULT_KEY, None),
	("upper-case", "HTTPS://WordBridge.Coseeing.ORG", DEFAULT_KEY, None),
	("default-port", "https://wordbridge.coseeing.org:443/", DEFAULT_KEY, None),
	("port-and-query", "https://h.test:8443/c?x=1", "https://h.test:8443/c?x=1", None),
	("loopback-name", "http://localhost:8000", "http://localhost:8000/", None),
	("loopback-v4", "http://127.0.0.1:8000/", "http://127.0.0.1:8000/", None),
	("loopback-v6", "http://[::1]:8000/", "http://[::1]:8000/", None),
	("loopback-upper", "http://LOCALHOST", "http://localhost/", None),
	("max-length", MAX_LENGTH_URL, MAX_LENGTH_URL, None),
	("http-remote", "http://example.com", "", "insecure_scheme"),
	("http-private-ip", "http://10.0.0.5", "", "insecure_scheme"),
	("ftp", "ftp://x", "", "invalid"),
	("no-scheme", "wordbridge.coseeing.org", "", "invalid"),
	("no-host", "https://", "", "invalid"),
	("userinfo", "https://user:pass@h.test/", "", "invalid"),
	("fragment", "https://h.test/#top", "", "invalid"),
	("empty-fragment", "https://h.test/#", "", "invalid"),
	("port-range", "https://h.test:99999/", "", "invalid"),
	("port-text", "https://h.test:abc/", "", "invalid"),
	("inner-space", "https://h.test/a b", "", "invalid"),
	("control", "https://h.test/\x00", "", "invalid"),
	("ideographic-space-inside", "https://wordbridge.coseeing.org　/x", "", "invalid"),
	("fullwidth-colon", "https：//wordbridge.coseeing.org", "", "invalid"),
	("bad-ipv6", "https://[::1", "", "invalid"),
	("too-long", MAX_LENGTH_URL + "a", "", "invalid"),
]


@pytest.mark.parametrize("text, key, error", [row[1:] for row in TABLE], ids=[row[0] for row in TABLE])
def test_validate_catalog_url_table(text, key, error):
	check = validate_catalog_url(text)

	assert check.url == text.strip()
	assert check.key == key
	assert check.error == error
	assert check.enabled is (error is None and text.strip() != "")


def test_the_max_length_row_is_exactly_at_the_limit():
	assert len(MAX_LENGTH_URL) == 2048


@pytest.mark.parametrize("value", [None, 5, b"https://x", "https://例子.測試/", "https://h.test/\ud800"])
def test_validate_catalog_url_never_raises(value):
	check = validate_catalog_url(value)

	assert isinstance(check, UrlCheck)
	if not isinstance(value, str):
		assert check.error == "invalid"
		assert check.enabled is False


def test_empty_path_and_slash_share_a_key():
	assert validate_catalog_url("https://h.test").key == validate_catalog_url("https://h.test/").key


@pytest.mark.parametrize("url, redacted", [
	("https://h.test:8443/secret?token=x", "https://h.test:8443"),
	("https://h.test/p", "https://h.test"),
	("http://[::1]:8000/x", "http://[::1]:8000"),
	("https://u:p@h.test/", "https://h.test"),
	("https://[::1", "<invalid url>"),
])
def test_redact_url(url, redacted):
	assert redact_url(url) == redacted


def test_default_catalog_url_is_valid_https():
	check = validate_catalog_url(DEFAULT_CATALOG_URL)

	assert check.enabled
	assert check.key.startswith("https://")
