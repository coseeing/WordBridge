import json
import threading

import pytest

from fake_http import BodyResponse
from plugin_modules import load_plugin_module


updater_module = load_plugin_module("catalog_updater")
cache_module = __import__(updater_module.__name__.rsplit(".", 1)[0] + ".lib.catalog.cache", fromlist=["CatalogCache"])
remote_module = __import__(updater_module.__name__.rsplit(".", 1)[0] + ".lib.catalog.remote", fromlist=["validate_catalog_url"])
CatalogUpdater = updater_module.CatalogUpdater
SUPPORTED = frozenset({"Anthropic", "DeepSeek", "Google", "Ollama", "OpenAI", "OpenRouter"})

URL_A = "https://a.test/catalog?token=secret-a"
URL_B = "https://b.test/catalog"


def _payload(model="gpt-remote", provider="OpenAI", url="https://api.openai.com/v1/responses", active=True):
	return {
		"schema_version": 1,
		"providers": {provider: {"label": provider, "url": url, "setting": {}, "timeout0": 10, "timeout_max": 60}},
		"models": [{"model": model, "provider": provider, "label": model, "active": active}],
	}


def _key(url):
	return remote_module.validate_catalog_url(url).key


class BundledSentinel:
	def load(self):
		return {"schema_version": 1, "coseeings": [{"model": "default", "label": "default"}]}, ()


def FakeResponse(status_code=200, body=b""):
	return BodyResponse(body, status_code=status_code, headers={})


class FakeThread:
	def __init__(self, target, args):
		self.target = target
		self.args = args

	def run(self):
		self.target(*self.args)

	def is_alive(self):
		return False


class FakeLog:
	def __init__(self):
		self.records = []

	def info(self, *args):
		self.records.append(("info",) + args)

	def warning(self, *args):
		self.records.append(("warning",) + args)

	def text(self):
		return "\n".join(" ".join(str(part) for part in record) for record in self.records)


class SpyCache:
	def __init__(self, inner):
		self.inner = inner
		self.loads = []
		self.stores = []

	def load(self, url_key):
		self.loads.append(url_key)
		return self.inner.load(url_key)

	def store(self, url_key, document):
		self.stores.append(url_key)
		return self.inner.store(url_key, document)


class Harness:
	def __init__(self, tmp_path, responses=None, schedule=None):
		self.responses = responses if responses is not None else {}
		self.requests = []
		self.threads = []
		self.queue = []
		self.installed = []
		self.shutdown = threading.Event()
		self.log = FakeLog()
		self.cache = SpyCache(cache_module.CatalogCache(tmp_path / "catalog" / "remote-catalog.json", can_write=lambda: True))
		self.updater = CatalogUpdater(
			bundled_source=BundledSentinel(),
			cache=self.cache,
			runnable_providers=SUPPORTED,
			http_get=self.http_get,
			post_to_ui=lambda function, *args: self.queue.append((function, args)),
			install=self.installed.append,
			shutdown=self.shutdown,
			log=self.log,
			start_thread=self.start_thread,
			schedule=schedule,
		)

	def http_get(self, url, **kwargs):
		self.requests.append(url)
		response = self.responses[url]
		if isinstance(response, Exception):
			raise response
		# A streamed body can be read once; every request gets its own.
		return response.fresh()

	def start_thread(self, target, args):
		thread = FakeThread(target, args)
		self.threads.append(thread)
		return thread

	def deliver(self):
		queue, self.queue = self.queue, []
		for function, args in queue:
			function(*args)

	def seed_cache(self, url, document):
		self.cache.inner.store(_key(url), document)

	def status(self):
		status = self.updater.status()
		return (status.source, status.fetch)


def _ok(document):
	return FakeResponse(body=json.dumps(document).encode("utf8"))


def _ids(catalog):
	return [entry.corrector_config_id for entry in catalog.models]


def test_startup_with_a_cache_uses_it(tmp_path):
	h = Harness(tmp_path)
	h.seed_cache(URL_A, _payload("cached"))

	catalog = h.updater.initial_catalog(URL_A)

	assert _ids(catalog) == ["cached&OpenAI"]
	assert h.status() == ("cache", "running")
	assert h.threads == []


def test_startup_without_a_cache_is_bundled_only(tmp_path):
	h = Harness(tmp_path)

	catalog = h.updater.initial_catalog(URL_A)

	assert catalog.models == ()
	assert catalog.labels_for("Coseeing") == ("default",)
	assert h.status() == ("none", "running")


def test_a_cached_payload_failing_acceptance_is_ignored(tmp_path):
	h = Harness(tmp_path)
	h.seed_cache(URL_A, _payload("cached", active=False))

	catalog = h.updater.initial_catalog(URL_A)

	assert catalog.models == ()
	assert h.status() == ("none", "running")
	# Spec section 10: a cached payload failing acceptance is an unreadable
	# cache, logged with the type of problem only.
	assert [record for record in h.log.records if record[0] == "warning"] == [
		("warning", "WordBridge: catalog cache problem code=%s type=%s", "unreadable_cache", "remote_no_models"),
	]


def test_a_cached_document_with_a_wrong_schema_is_ignored(tmp_path):
	h = Harness(tmp_path)
	h.seed_cache(URL_A, dict(_payload("cached"), schema_version=2))

	assert h.updater.initial_catalog(URL_A).models == ()
	assert h.status() == ("none", "running")


def test_a_successful_refresh_posts_an_install_and_writes_the_cache(tmp_path):
	h = Harness(tmp_path, {URL_A: _ok(_payload("fresh"))})
	h.updater.initial_catalog(URL_A)

	h.updater.refresh(URL_A)
	assert h.installed == []
	h.threads[0].run()
	assert h.installed == []
	h.deliver()

	assert [_ids(catalog) for catalog in h.installed] == [["fresh&OpenAI"]]
	assert h.status() == ("fetched", "succeeded")
	assert h.cache.inner.load(_key(URL_A))[0] == _payload("fresh")
	assert h.requests == [URL_A]


def test_a_failed_refresh_keeps_the_catalog_and_cache(tmp_path):
	h = Harness(tmp_path, {URL_A: FakeResponse(status_code=500)})
	h.seed_cache(URL_A, _payload("cached"))
	h.updater.initial_catalog(URL_A)

	h.updater.refresh(URL_A)
	h.threads[0].run()
	h.deliver()

	assert h.installed == []
	assert h.status() == ("cache", "failed")
	assert h.cache.inner.load(_key(URL_A))[0] == _payload("cached")
	assert ("warning", "WordBridge: catalog fetch failed host=%s code=%s type=%s", "https://a.test", "remote_http_status", "500") in h.log.records


def test_a_rejected_payload_is_not_cached_or_installed(tmp_path):
	h = Harness(tmp_path, {URL_A: _ok(_payload("bad", url="https://evil.test/v1"))})
	h.updater.initial_catalog(URL_A)

	h.updater.refresh(URL_A)
	h.threads[0].run()
	h.deliver()

	assert h.installed == []
	assert h.cache.stores == []
	assert h.status() == ("none", "failed")


def test_out_of_order_completion_installs_only_the_newer(tmp_path):
	h = Harness(tmp_path, {URL_A: _ok(_payload("fresh"))})
	h.updater.initial_catalog(URL_A)
	h.updater.refresh(URL_A)
	h.updater.refresh(URL_A)

	h.threads[1].run()
	h.deliver()
	h.responses[URL_A] = _ok(_payload("stale"))
	h.threads[0].run()
	h.deliver()

	assert [_ids(catalog) for catalog in h.installed] == [["fresh&OpenAI"]]
	assert h.cache.stores == [_key(URL_A)]
	assert h.cache.inner.load(_key(URL_A))[0] == _payload("fresh")


def test_shutdown_before_completion_posts_and_writes_nothing(tmp_path):
	h = Harness(tmp_path, {URL_A: _ok(_payload("fresh"))})
	h.updater.initial_catalog(URL_A)
	h.updater.refresh(URL_A)

	h.shutdown.set()
	h.threads[0].run()

	assert h.queue == []
	assert h.cache.stores == []


def test_apply_after_shutdown_does_nothing(tmp_path):
	h = Harness(tmp_path, {URL_A: _ok(_payload("fresh"))})
	h.updater.initial_catalog(URL_A)
	h.updater.refresh(URL_A)
	h.threads[0].run()

	h.shutdown.set()
	h.deliver()

	assert h.installed == []
	assert h.status() == ("none", "running")


def test_a_url_change_installs_bundled_plus_new_cache_at_once(tmp_path):
	h = Harness(tmp_path, {URL_A: _ok(_payload("a")), URL_B: _ok(_payload("b"))})
	h.seed_cache(URL_A, _payload("cached-a"))
	h.updater.initial_catalog(URL_A)

	h.updater.refresh(URL_B)

	# D8: the live catalog leaves A at once; there is no cache for B.
	assert [_ids(catalog) for catalog in h.installed] == [[]]
	assert h.status() == ("none", "running")
	assert len(h.threads) == 1


def test_refresh_with_the_same_url_does_not_reinstall(tmp_path):
	h = Harness(tmp_path, {URL_A: _ok(_payload("a"))})
	h.updater.initial_catalog(URL_A)

	h.updater.refresh("  " + URL_A + "  ")

	assert h.installed == []
	assert len(h.threads) == 1


def test_url_changed_back_before_fetches_complete_installs_only_the_last(tmp_path):
	h = Harness(tmp_path, {URL_A: _ok(_payload("fresh-a")), URL_B: _ok(_payload("fresh-b"))})
	h.seed_cache(URL_A, _payload("cached-a"))
	h.updater.initial_catalog(URL_A)

	h.updater.refresh(URL_A)  # startup fetch, generation 1
	h.updater.refresh(URL_B)  # generation 2: bundled only at once
	h.updater.refresh(URL_A)  # generation 3: back to A's cache at once

	assert [_ids(catalog) for catalog in h.installed] == [[], ["cached-a&OpenAI"]]
	assert h.status() == ("cache", "running")

	for thread in (h.threads[1], h.threads[0], h.threads[2]):
		thread.run()
		h.deliver()

	assert [_ids(catalog) for catalog in h.installed] == [[], ["cached-a&OpenAI"], ["fresh-a&OpenAI"]]
	assert h.cache.stores == [_key(URL_A)]
	assert h.cache.inner.load(_key(URL_B)) == (None, ())
	assert h.status() == ("fetched", "succeeded")


def test_an_empty_url_starts_no_thread_and_reads_no_cache(tmp_path):
	h = Harness(tmp_path)

	catalog = h.updater.initial_catalog("")
	h.updater.refresh("")

	assert catalog.models == ()
	assert h.threads == []
	assert h.cache.loads == []
	assert h.requests == []
	assert h.status() == ("none", "off")


def test_an_invalid_stored_url_is_invalid_and_logged_once(tmp_path):
	h = Harness(tmp_path)

	h.updater.initial_catalog("http://example.com/p?token=x")
	h.updater.refresh("http://example.com/p?token=x")

	assert h.status() == ("none", "invalid")
	assert h.threads == []
	assert h.cache.loads == []
	invalid_lines = [record for record in h.log.records if "invalid" in str(record[1])]
	assert len(invalid_lines) == 1
	assert "token" not in h.log.text()


def test_switching_to_an_empty_url_installs_bundled_only(tmp_path):
	h = Harness(tmp_path)
	h.seed_cache(URL_A, _payload("cached-a"))
	h.updater.initial_catalog(URL_A)

	h.updater.refresh("")

	assert [_ids(catalog) for catalog in h.installed] == [[]]
	assert h.status() == ("none", "off")
	assert h.threads == []


def test_logs_never_contain_path_query_or_error_text(tmp_path):
	h = Harness(tmp_path, {URL_A: OSError("connect failed for https://a.test/catalog?token=secret-a")})
	h.updater.initial_catalog(URL_A)
	h.updater.refresh(URL_A)
	h.threads[0].run()
	h.deliver()

	text = h.log.text()
	assert "a.test" in text
	assert "/catalog" not in text
	assert "token" not in text
	assert "secret" not in text
	assert "connect failed" not in text
	assert "OSError" in text


def test_a_success_log_names_the_host_bytes_and_models(tmp_path):
	body = json.dumps(_payload("fresh")).encode("utf8")
	h = Harness(tmp_path, {URL_A: FakeResponse(body=body)})
	h.updater.initial_catalog(URL_A)
	h.updater.refresh(URL_A)
	h.threads[0].run()
	h.deliver()

	assert ("info", "WordBridge: catalog fetched host=%s bytes=%d models=%d", "https://a.test", len(body), 1) in h.log.records


def test_an_unexpected_exception_in_the_thread_reports_failure(tmp_path, monkeypatch):
	h = Harness(tmp_path, {URL_A: _ok(_payload("fresh"))})
	h.updater.initial_catalog(URL_A)

	def broken(body):
		raise RuntimeError("payload https://a.test/catalog?token=secret-a")

	monkeypatch.setattr(updater_module, "parse_remote_payload", broken)
	h.updater.refresh(URL_A)
	h.threads[0].run()
	h.deliver()

	assert h.status() == ("none", "failed")
	assert "RuntimeError" in h.log.text()
	assert "secret" not in h.log.text()


def test_the_thread_property_is_the_latest_started(tmp_path):
	h = Harness(tmp_path, {URL_A: _ok(_payload("a"))})
	h.updater.initial_catalog(URL_A)
	assert h.updater.thread is None

	h.updater.refresh(URL_A)
	h.updater.refresh(URL_A)

	assert h.updater.thread is h.threads[1]


def test_module_request_refresh_is_a_no_op_without_an_updater():
	updater_module.uninstall()

	updater_module.request_refresh(URL_A)

	assert updater_module.status() is None


def test_module_functions_delegate_to_the_installed_updater(tmp_path):
	h = Harness(tmp_path, {URL_B: _ok(_payload("b"))})
	h.updater.initial_catalog(URL_A)
	updater_module.install(h.updater)
	try:
		updater_module.request_refresh(URL_B)

		assert len(h.threads) == 1
		assert updater_module.status() == h.updater.status()
	finally:
		updater_module.uninstall()
	assert updater_module.status() is None


def test_the_production_thread_starter_makes_a_named_daemon(monkeypatch):
	started = []

	class RecordingThread:
		def __init__(self, **kwargs):
			self.kwargs = kwargs

		def start(self):
			started.append(self.kwargs)

	monkeypatch.setattr(updater_module.threading, "Thread", RecordingThread)

	thread = updater_module.start_daemon_thread(print, ("x",))

	assert started == [{"target": print, "args": ("x",), "name": "wordbridge-catalog-fetch", "daemon": True}]
	assert isinstance(thread, RecordingThread)


@pytest.fixture(autouse=True)
def _no_installed_updater():
	updater_module.uninstall()
	yield
	updater_module.uninstall()


def test_a_result_posted_before_a_url_change_is_not_installed(tmp_path):
	# A's thread has already posted _apply, but the wx queue has not run it
	# yet when the user saves URL B: only the D8 switch to B may happen.
	h = Harness(tmp_path, {URL_A: _ok(_payload("fresh-a")), URL_B: _ok(_payload("fresh-b"))})
	h.updater.initial_catalog(URL_A)
	h.updater.refresh(URL_A)
	h.threads[0].run()
	assert len(h.queue) == 1

	h.updater.refresh(URL_B)
	h.deliver()

	assert [_ids(catalog) for catalog in h.installed] == [[]]
	assert h.status() == ("none", "running")
	# The live key is still B: refreshing B again switches nothing.
	h.updater.refresh(URL_B)
	assert len(h.installed) == 1


def test_switching_to_an_empty_url_discards_the_in_flight_fetch(tmp_path):
	h = Harness(tmp_path, {URL_A: _ok(_payload("fresh-a"))})
	h.updater.initial_catalog(URL_A)
	h.updater.refresh(URL_A)

	h.updater.refresh("")
	h.threads[0].run()
	h.deliver()

	assert [_ids(catalog) for catalog in h.installed] == [[]]
	assert h.status() == ("none", "off")
	assert h.cache.stores == []


def test_switching_to_an_invalid_url_discards_the_in_flight_fetch(tmp_path):
	h = Harness(tmp_path, {URL_A: _ok(_payload("fresh-a"))})
	h.updater.initial_catalog(URL_A)
	h.updater.refresh(URL_A)

	h.updater.refresh("http://example.com/")
	h.threads[0].run()
	h.deliver()

	assert [_ids(catalog) for catalog in h.installed] == [[]]
	assert h.status() == ("none", "invalid")


class RaisingStoreCache(SpyCache):
	def store(self, url_key, document):
		self.stores.append(url_key)
		raise OSError("disk gone: C:\\Users\\someone\\secret")


class FailingStoreCache(SpyCache):
	def store(self, url_key, document):
		self.stores.append(url_key)
		return (cache_module.CatalogIssue("cache_write_failed", "cache", "OSError"),)


@pytest.mark.parametrize("cache_class", [RaisingStoreCache, FailingStoreCache], ids=["raises", "reports"])
def test_a_failed_cache_write_still_installs_the_catalog(tmp_path, cache_class):
	h = Harness(tmp_path, {URL_A: _ok(_payload("fresh"))})
	h.updater._cache = h.cache = cache_class(h.cache.inner)
	h.updater.initial_catalog(URL_A)
	h.updater.refresh(URL_A)

	h.threads[0].run()
	h.deliver()

	assert [_ids(catalog) for catalog in h.installed] == [["fresh&OpenAI"]]
	assert h.status() == ("fetched", "succeeded")
	assert h.cache.stores == [_key(URL_A)]
	assert "cache_write_failed" in h.log.text()
	assert "secret" not in h.log.text()


@pytest.mark.parametrize("url", [
	remote_module.DEFAULT_CATALOG_URL,
	"HTTPS://WordBridge.Coseeing.ORG",
], ids=["default-url", "upper-case-host"])
def test_the_cache_is_stored_under_the_key_and_used_at_the_next_start(tmp_path, url):
	# The URL as typed is not the key here (no trailing slash, upper case),
	# so a cache stored under the URL would never be found again.
	key = "https://wordbridge.coseeing.org/"
	assert _key(url) == key != url
	h = Harness(tmp_path, {url: _ok(_payload("fresh"))})
	h.updater.initial_catalog(url)
	h.updater.refresh(url)
	h.threads[0].run()
	h.deliver()

	assert h.cache.stores == [key]
	assert h.cache.inner.load(key)[0] == _payload("fresh")

	restarted = Harness(tmp_path)
	catalog = restarted.updater.initial_catalog(url)
	assert _ids(catalog) == ["fresh&OpenAI"]
	assert restarted.status() == ("cache", "running")


def _logged_lines(h):
	return [record[1] % record[2:] for record in h.log.records]


def test_a_huge_remote_detail_is_logged_bounded_on_fetch_failure(tmp_path):
	# A remote schema_version is repr()'d into the issue detail; JSON allows
	# a 4000-digit integer.
	body = b'{"schema_version": ' + b"9" * 4000 + b', "providers": {}, "models": []}'
	h = Harness(tmp_path, {URL_A: FakeResponse(body=body)})
	h.updater.initial_catalog(URL_A)
	h.updater.refresh(URL_A)
	h.threads[0].run()
	h.deliver()

	[failure] = [line for line in _logged_lines(h) if "catalog fetch failed" in line]
	assert "code=remote_schema_version" in failure
	assert len(failure) < 400


def test_a_huge_cached_detail_is_logged_bounded(tmp_path):
	h = Harness(tmp_path)
	h.seed_cache(URL_A, dict(_payload("cached"), schema_version=int("9" * 4000)))

	h.updater.initial_catalog(URL_A)

	[problem] = [line for line in _logged_lines(h) if "catalog cache problem" in line]
	assert "remote_schema_version" in problem
	assert len(problem) < 400


class RaisingBundled:
	def load(self):
		raise OSError("catalog.json unreadable")


def test_a_failing_bundled_source_is_not_logged_as_a_bad_cache_payload(tmp_path):
	h = Harness(tmp_path)
	h.seed_cache(URL_A, _payload("cached"))
	h.updater._bundled_source = RaisingBundled()

	catalog = h.updater.initial_catalog(URL_A)

	assert catalog.degraded
	assert h.status() == ("none", "running")
	assert (
		"warning", "WordBridge: catalog cache problem code=%s type=%s", "unreadable_cache", "bundled_source_failed",
	) in h.log.records


SOURCE_LOG = "WordBridge: catalog source=%s fetch=%s host=%s"


def _source_lines(h):
	return [record[2:] for record in h.log.records if record[:2] == ("info", SOURCE_LOG)]


def test_startup_logs_the_source_in_use(tmp_path):
	# Spec section 17.6 items 6 and 7 check in the log whether the cache was used.
	with_cache = Harness(tmp_path)
	with_cache.seed_cache(URL_A, _payload("cached"))
	with_cache.updater.initial_catalog(URL_A)
	assert _source_lines(with_cache) == [("cache", "running", "https://a.test")]

	other_url = Harness(tmp_path)
	other_url.updater.initial_catalog(URL_B)
	assert _source_lines(other_url) == [("none", "running", "https://b.test")]


@pytest.mark.parametrize("url, fetch", [("", "off"), ("ftp://x", "invalid")], ids=["empty", "invalid"])
def test_startup_without_a_usable_url_logs_no_host(tmp_path, url, fetch):
	h = Harness(tmp_path)
	h.updater.initial_catalog(url)

	assert _source_lines(h) == [("none", fetch, "(none)")]


def test_a_url_change_logs_the_new_source_and_a_same_url_refresh_does_not(tmp_path):
	h = Harness(tmp_path, {URL_A: FakeResponse(status_code=500), URL_B: FakeResponse(status_code=500)})
	h.seed_cache(URL_B, _payload("cached"))
	h.updater.initial_catalog(URL_A)
	h.updater.refresh(URL_A)
	h.updater.refresh(URL_B)

	assert _source_lines(h) == [("none", "running", "https://a.test"), ("cache", "running", "https://b.test")]
