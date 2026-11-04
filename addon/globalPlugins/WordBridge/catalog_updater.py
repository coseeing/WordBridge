"""Fetches the remote catalog and keeps the live catalog up to date.

Imports only the standard library and .lib.catalog. NVDA's `requests`, wx,
config and the log are injected by __init__.py, so importing this module has
no side effects and tests never touch the network.
"""

from dataclasses import dataclass
import time

from .lib.catalog.model import CatalogIssue
from .lib.catalog.remote import CHUNK_BYTES, FETCH_DEADLINE_SECONDS, FETCH_TIMEOUT, MAX_PAYLOAD_BYTES


_FETCH = "fetch"


@dataclass(frozen=True)
class FetchResult:
	body: bytes | None
	issue: CatalogIssue | None


def _failed(code: str, detail: str) -> FetchResult:
	return FetchResult(body=None, issue=CatalogIssue(code, _FETCH, detail))


def _declared_length(headers):
	"""Content-Length as an int, or None when it is absent or unusable."""
	try:
		value = int(headers.get("Content-Length"))
	except (TypeError, ValueError, AttributeError):
		return None
	return value if value >= 0 else None


def fetch_payload(url: str, *, http_get, clock=time.monotonic) -> FetchResult:
	"""GET the catalog. Never raises.

	No credentials, cookies or identifiers are sent, redirects are not
	followed (a 3xx could downgrade to http), and TLS verification is left at
	requests' default. Error details are exception type names only:
	requests' messages contain the full URL.
	"""
	start = clock()

	def past_deadline():
		return clock() - start > FETCH_DEADLINE_SECONDS

	try:
		with http_get(
			url,
			stream=True,
			timeout=FETCH_TIMEOUT,
			allow_redirects=False,
			headers={"Accept": "application/json"},
		) as response:
			if past_deadline():
				return _failed("remote_timeout", f"deadline {FETCH_DEADLINE_SECONDS}s")
			if response.status_code != 200:
				return _failed("remote_http_status", str(response.status_code))
			declared = _declared_length(response.headers)
			if declared is not None and declared > MAX_PAYLOAD_BYTES:
				return _failed("remote_too_large", f"limit {MAX_PAYLOAD_BYTES}")
			chunks = []
			total = 0
			for chunk in response.iter_content(CHUNK_BYTES):
				if chunk:
					total += len(chunk)
					if total > MAX_PAYLOAD_BYTES:
						return _failed("remote_too_large", f"limit {MAX_PAYLOAD_BYTES}")
					chunks.append(chunk)
				if past_deadline():
					return _failed("remote_timeout", f"deadline {FETCH_DEADLINE_SECONDS}s")
			return FetchResult(body=b"".join(chunks), issue=None)
	except Exception as error:
		return _failed("remote_request_failed", type(error).__name__)
