"""The on-disk copy of the last accepted remote catalog.

One file, keyed by the URL it was fetched from, so a payload from one URL is
never shown for another. The payload is stored before allowlist filtering, so
whichever add-on version loads it re-applies its own rules. A corrupt file is
ignored, never deleted; the next successful fetch overwrites it.
"""

import json
import os
from pathlib import Path
import tempfile

from .model import CatalogIssue
from .remote import MAX_PAYLOAD_BYTES


CACHE_VERSION = 1
# The file is a re-serialisation of the payload plus a small wrapper (the
# url_key alone may be 2048 characters), so it may legitimately be larger
# than the payload limit itself.
MAX_CACHE_BYTES = 2 * MAX_PAYLOAD_BYTES
_LOCATION = "cache"


def _unreadable(detail: str) -> tuple:
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
			return _unreadable("file is larger than the limit")
		try:
			stored = json.loads(data)
		except Exception as error:
			return _unreadable(type(error).__name__)
		if not isinstance(stored, dict):
			return _unreadable(f"expected an object, got {type(stored).__name__}")
		if stored.get("cache_version") != CACHE_VERSION:
			return _unreadable("unknown cache_version")
		if not isinstance(stored.get("url_key"), str):
			return _unreadable("url_key is not a string")
		if not isinstance(stored.get("document"), dict):
			return _unreadable("document is not an object")
		if stored["url_key"] != url_key:
			return None, ()
		return stored["document"], ()

	def store(self, url_key: str, document: dict) -> tuple:
		"""Write atomically. Returns the issues; never raises."""
		try:
			allowed = bool(self._can_write())
		except Exception:
			allowed = False
		if not allowed:
			return ()
		temporary = None
		try:
			body = json.dumps(
				{"cache_version": CACHE_VERSION, "url_key": url_key, "document": document},
				ensure_ascii=False,
			).encode("utf8")
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
		except Exception as error:
			if temporary is not None:
				try:
					os.unlink(temporary)
				except OSError:
					pass
			return (CatalogIssue("cache_write_failed", _LOCATION, type(error).__name__),)
		return ()
