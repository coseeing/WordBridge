import json

import pytest

import lib.catalog.cache as cache_module
from lib.catalog.cache import CACHE_VERSION, MAX_CACHE_BYTES, CatalogCache


KEY = "https://wordbridge.coseeing.org/"
DOCUMENT = {"schema_version": 1, "providers": {}, "models": [{"model": "m", "label": "模型"}]}


def _path(tmp_path):
	return tmp_path / "workspace" / "catalog" / "remote-catalog.json"


def _cache(tmp_path, can_write=lambda: True):
	return CatalogCache(_path(tmp_path), can_write=can_write)


def _codes(issues):
	return [issue.code for issue in issues]


def test_round_trip(tmp_path):
	cache = _cache(tmp_path)

	assert cache.store(KEY, DOCUMENT) == ()
	assert cache.load(KEY) == (DOCUMENT, ())
	stored = json.loads(_path(tmp_path).read_text(encoding="utf8"))
	assert stored == {"cache_version": CACHE_VERSION, "url_key": KEY, "document": DOCUMENT}


def test_a_missing_file_is_no_cache_and_no_issue(tmp_path):
	assert _cache(tmp_path).load(KEY) == (None, ())


def test_another_url_key_is_not_used(tmp_path):
	cache = _cache(tmp_path)
	cache.store(KEY, DOCUMENT)
	before = _path(tmp_path).read_bytes()

	assert cache.load("http://localhost:8000/") == (None, ())
	assert _path(tmp_path).read_bytes() == before


@pytest.mark.parametrize("content", [
	b"{not json",
	b"[]",
	b'{"cache_version": 2, "url_key": "k", "document": {}}',
	b'{"cache_version": 1, "url_key": 5, "document": {}}',
	b'{"cache_version": 1, "url_key": "k", "document": []}',
], ids=["not-json", "not-object", "cache-version", "url-key-type", "document-type"])
def test_a_corrupt_cache_is_ignored_and_left_in_place(tmp_path, content):
	path = _path(tmp_path)
	path.parent.mkdir(parents=True)
	path.write_bytes(content)

	document, issues = _cache(tmp_path).load("k")

	assert document is None
	assert [(issue.code, issue.location) for issue in issues] == [("unreadable_cache", "cache")]
	assert path.read_bytes() == content


def test_a_file_larger_than_the_limit_is_ignored(tmp_path):
	path = _path(tmp_path)
	path.parent.mkdir(parents=True)
	path.write_bytes(b" " * (MAX_CACHE_BYTES + 1))

	document, issues = _cache(tmp_path).load(KEY)

	assert document is None
	assert _codes(issues) == ["unreadable_cache"]


def test_a_failing_replace_keeps_the_old_file_and_leaves_no_temp_file(tmp_path, monkeypatch):
	cache = _cache(tmp_path)
	cache.store(KEY, DOCUMENT)
	before = _path(tmp_path).read_bytes()

	def failing_replace(source, target):
		raise OSError("disk full")

	monkeypatch.setattr(cache_module.os, "replace", failing_replace)
	issues = cache.store(KEY, {"schema_version": 1, "providers": {}, "models": []})

	assert [(issue.code, issue.location, issue.detail) for issue in issues] == [
		("cache_write_failed", "cache", "OSError"),
	]
	assert _path(tmp_path).read_bytes() == before
	assert sorted(path.name for path in _path(tmp_path).parent.iterdir()) == ["remote-catalog.json"]


def test_can_write_false_writes_nothing(tmp_path):
	assert _cache(tmp_path, can_write=lambda: False).store(KEY, DOCUMENT) == ()
	assert not _path(tmp_path).parent.exists()


def test_can_write_raising_writes_nothing(tmp_path):
	def broken():
		raise RuntimeError("NVDAState unavailable")

	assert _cache(tmp_path, can_write=broken).store(KEY, DOCUMENT) == ()
	assert not _path(tmp_path).parent.exists()


def test_the_directory_is_created_only_by_store(tmp_path):
	cache = _cache(tmp_path)
	cache.load(KEY)
	assert not _path(tmp_path).parent.exists()

	cache.store(KEY, DOCUMENT)
	assert _path(tmp_path).is_file()


def test_a_parent_that_is_a_file_reports_cache_write_failed(tmp_path):
	blocker = tmp_path / "workspace"
	blocker.write_text("not a directory", encoding="utf8")

	issues = _cache(tmp_path).store(KEY, DOCUMENT)

	assert _codes(issues) == ["cache_write_failed"]
	assert _cache(tmp_path).load(KEY)[0] is None
