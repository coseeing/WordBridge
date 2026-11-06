"""The on-disk copy of the last accepted remote catalog.

One file, keyed by the URL it was fetched from, so a payload from one URL is
never shown for another. The payload is stored as fetched, so whichever
add-on version loads it applies its own bundled providers and rules. A
corrupt file is ignored, never deleted; the next successful fetch overwrites
it.
"""

import json
import os
import tempfile
from pathlib import Path

from .model import CatalogIssue
from .remote import MAX_PAYLOAD_BYTES

CACHE_VERSION = 1
# The file is a re-serialisation of the payload plus a small wrapper (the
# url_key alone may be 2048 characters), so it may legitimately be larger
# than the payload limit itself. Re-serialisation is not bounded by any
# fixed factor (floats can grow), so store() also refuses a body over this
# limit: a file the next start could not read must never replace a good one.
MAX_CACHE_BYTES = 2 * MAX_PAYLOAD_BYTES
_LOCATION = "cache"


def _unreadable(detail: str) -> tuple:
	# detail is logged as the problem's type (spec section 10, "type only"):
	# a short code or an exception type name.
	return None, (CatalogIssue("unreadable_cache", _LOCATION, detail),)


class CatalogCache:
	def __init__(self, path, *, can_write):
		"""can_write is NVDAState.shouldWriteToDisk in production: never from
		secure mode or the launcher. The directory is created only by store().
		"""
		self.path = Path(path)
		self._can_write = can_write

	def load(self, url_key: str) -> tuple:
		"""Returns (document, issues). (None, ()) when there is no cache for url_key."""
		try:
			with self.path.open("rb") as handle:
				data = handle.read(MAX_CACHE_BYTES + 1)
		except FileNotFoundError:
			return None, ()
		except OSError as error:
			return _unreadable(type(error).__name__)
		if len(data) > MAX_CACHE_BYTES:
			return _unreadable("too_large")
		try:
			stored = json.loads(data)
		except Exception as error:  # noqa: BLE001
			return _unreadable(type(error).__name__)
		if not isinstance(stored, dict):
			return _unreadable("not_an_object")
		if stored.get("cache_version") != CACHE_VERSION:
			return _unreadable("unknown_cache_version")
		if not isinstance(stored.get("url_key"), str):
			return _unreadable("url_key_not_a_string")
		if not isinstance(stored.get("document"), dict):
			return _unreadable("document_not_an_object")
		if stored["url_key"] != url_key:
			return None, ()
		return stored["document"], ()

	def store(self, url_key: str, document: dict) -> tuple:
		"""Write atomically. Returns the issues; never raises."""
		try:
			allowed = bool(self._can_write())
		except Exception:  # noqa: BLE001
			allowed = False
		if not allowed:
			return ()
		temporary = None
		try:
			# surrogatepass: a "\ud800" escape in the payload is a lone
			# surrogate after json.loads(), which strict UTF-8 cannot encode;
			# json.loads(bytes) in load() decodes with surrogatepass as well.
			body = json.dumps(
				{"cache_version": CACHE_VERSION, "url_key": url_key, "document": document},
				ensure_ascii=False,
				separators=(",", ":"),
			).encode("utf8", "surrogatepass")
			if len(body) > MAX_CACHE_BYTES:
				return (CatalogIssue("cache_write_failed", _LOCATION, "too_large"),)
			self.path.parent.mkdir(parents=True, exist_ok=True)
			with tempfile.NamedTemporaryFile(
				dir=self.path.parent,
				prefix="remote-catalog.",
				suffix=".tmp",
				delete=False,
			) as handle:
				temporary = handle.name
				handle.write(body)
				handle.flush()
				os.fsync(handle.fileno())
			os.replace(temporary, self.path)
		except Exception as error:  # noqa: BLE001
			if temporary is not None:
				try:
					os.unlink(temporary)
				except OSError:
					pass
			return (CatalogIssue("cache_write_failed", _LOCATION, type(error).__name__),)
		return ()
