"""Rules for the remote catalog: the URL it comes from and what it may contain.

Everything here is pure and standard-library-only, like the rest of
lib/catalog. The HTTP request itself lives in catalog_updater.py, which gets
NVDA's own `requests` injected.
"""

from dataclasses import dataclass
import json
from urllib.parse import urlsplit

from .document import SCHEMA_VERSION
from .model import CatalogIssue


DEFAULT_CATALOG_URL = "https://wordbridge.coseeing.org"
MAX_URL_LENGTH = 2048
# Plain http is allowed only for a catalog served from this machine (the
# local development server).
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

MAX_PAYLOAD_BYTES = 1_048_576
# (connect, read) seconds, as requests takes them.
FETCH_TIMEOUT = (5, 10)
# Checked after every socket read (catalog_updater reads with raw.read1()),
# so a server dripping bytes holds the fetch thread for at most this plus one
# read timeout.
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
	kept. Never raises: anything but a str (bytes would give a bytes
	hostname) is redacted as invalid.
	"""
	if not isinstance(url, str):
		return _INVALID_REDACTED
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


LOG_TEXT_LIMIT = 200


def loggable(value) -> str:
	"""`value` as log text: one line of at most LOG_TEXT_LIMIT characters plus "...".

	Catalog issue locations and details can carry remote text -- a provider
	name, a host, a repr()'d value -- of up to the payload size. Every
	character that is not printable (newline, ESC, ...) is escaped the way
	repr() escapes it, so remote text can never start a forged log line, and
	escapes count toward the limit. Never raises.
	"""
	try:
		text = value if isinstance(value, str) else repr(value)
	except Exception:
		text = f"<{type(value).__name__}>"
	pieces = []
	length = 0
	for ch in text:
		piece = ch if ch.isprintable() else repr(ch)[1:-1]
		if length + len(piece) > LOG_TEXT_LIMIT:
			return "".join(pieces) + "..."
		pieces.append(piece)
		length += len(piece)
	return "".join(pieces)


def _issue(code: str, detail: str) -> tuple:
	return (CatalogIssue(code, "payload", detail),)


def check_remote_document(document) -> tuple:
	"""The document-level checks of a remote payload; () when it passes.

	An object with schema_version 1 and a models list. Every other key,
	providers included, is ignored: provider entries are bundled with the
	add-on and the overlay never reads them from the payload, so their
	presence decides nothing. Breaking format changes go through
	schema_version, so a new optional key never refuses a payload.
	Entry-level problems are build_catalog()'s, and only drop entries. Both
	a freshly fetched payload and a cached one go through this, by way of
	overlay.accept_remote_document().
	"""
	if not isinstance(document, dict):
		return _issue("remote_malformed", f"expected an object, got {type(document).__name__}")
	version = document.get("schema_version")
	# type() first: 1.0 == 1 and True == 1. build_catalog() keeps its looser
	# check, which only ever sees the bundled file and the overlay's own
	# schema_version 1.
	if type(version) is not int or version != SCHEMA_VERSION:
		shown = repr(version) if version is None or type(version) in (int, float, bool) else type(version).__name__
		return _issue("remote_schema_version", f"expected {SCHEMA_VERSION}, got {shown}")
	if not isinstance(document.get("models"), list):
		return _issue("remote_malformed", "models must be a list")
	return ()


def parse_remote_payload(body) -> tuple:
	"""Returns (document, issues); document is None when the payload is rejected.

	JSON decoding plus check_remote_document(). Issue details carry type
	names, never any part of the body.
	"""
	try:
		document = json.loads(body)
	except Exception as error:
		# ValueError and UnicodeDecodeError for bad text, RecursionError for
		# deep nesting: every one of them is a malformed payload.
		return None, _issue("remote_malformed", type(error).__name__)
	issues = check_remote_document(document)
	if issues:
		return None, issues
	return document, ()
