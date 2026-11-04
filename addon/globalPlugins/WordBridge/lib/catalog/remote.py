"""Rules for the remote catalog: the URL it comes from and what it may contain.

Everything here is pure and standard-library-only, like the rest of
lib/catalog. The HTTP request itself lives in catalog_updater.py, which gets
NVDA's own `requests` injected.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit


DEFAULT_CATALOG_URL = "https://wordbridge.coseeing.org"
MAX_URL_LENGTH = 2048
# Plain http is allowed only for a catalog served from this machine (the
# local development server).
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

MAX_PAYLOAD_BYTES = 1_048_576
# (connect, read) seconds, as requests takes them.
FETCH_TIMEOUT = (5, 10)
# Checked between chunks, so a server dripping bytes cannot hold the fetch
# thread for long.
FETCH_DEADLINE_SECONDS = 20
CHUNK_BYTES = 65536

_DEFAULT_PORTS = {"https": 443, "http": 80}
_INVALID = "invalid"
_INSECURE_SCHEME = "insecure_scheme"
_INVALID_REDACTED = "<invalid url>"


@dataclass(frozen=True)
class UrlCheck:
	"""The result of validate_catalog_url().

	url is the stripped text, sent as typed. key is the comparison and cache
	key, and is "" whenever the remote catalog is off or the URL is invalid.
	error is None, "invalid" or "insecure_scheme".
	"""

	url: str
	key: str
	error: str | None

	@property
	def enabled(self) -> bool:
		return self.error is None and self.url != ""


def _host_text(host: str) -> str:
	return f"[{host}]" if ":" in host else host


def _split(text: str):
	"""urlsplit plus the .port read, which is where a bad port raises."""
	parts = urlsplit(text)
	return parts, parts.port


def validate_catalog_url(text) -> UrlCheck:
	"""Check a catalog URL typed by the user. Never raises."""
	if not isinstance(text, str):
		return UrlCheck(url="", key="", error=_INVALID)
	url = text.strip()
	if url == "":
		return UrlCheck(url="", key="", error=None)

	def invalid(error=_INVALID):
		return UrlCheck(url=url, key="", error=error)

	if len(url) > MAX_URL_LENGTH:
		return invalid()
	if any(ch.isspace() or not ch.isprintable() for ch in url):
		return invalid()
	# A fragment is never sent, and an empty one ("…/#") leaves no trace in
	# urlsplit(), so the character itself is what is checked.
	if "#" in url:
		return invalid()
	try:
		parts, port = _split(url)
	except ValueError:
		return invalid()
	scheme = parts.scheme.lower()
	if scheme not in _DEFAULT_PORTS:
		return invalid()
	host = parts.hostname
	if not host:
		return invalid()
	# User info would be sent to the server and would also end up in logs.
	if parts.username is not None or parts.password is not None:
		return invalid()
	if scheme == "http" and host not in LOOPBACK_HOSTS:
		return invalid(_INSECURE_SCHEME)

	key = f"{scheme}://{_host_text(host)}"
	if port is not None and port != _DEFAULT_PORTS[scheme]:
		key += f":{port}"
	key += parts.path or "/"
	if parts.query:
		key += f"?{parts.query}"
	return UrlCheck(url=url, key=key, error=None)


def redact_url(url) -> str:
	"""scheme://host[:port] -- the only form of a URL that is ever logged.

	A user-entered URL may carry a token in its path or query, so neither is
	kept. Never raises.
	"""
	try:
		parts, port = _split(url)
	except (TypeError, ValueError, AttributeError):
		return _INVALID_REDACTED
	if not parts.scheme or not parts.hostname:
		return _INVALID_REDACTED
	text = f"{parts.scheme.lower()}://{_host_text(parts.hostname)}"
	if port is not None:
		text += f":{port}"
	return text
