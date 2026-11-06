"""Fetches the remote catalog and keeps the live catalog up to date.

Imports only the standard library and .lib.catalog. NVDA's `requests`, wx,
config and the log are injected by __init__.py, so importing this module has
no side effects and tests never touch the network.
"""

import functools
import threading
import time
from dataclasses import dataclass

from .lib.catalog.model import COSEEING_GROUP, CatalogIssue
from .lib.catalog.overlay import accept_remote_document, has_local_items, load_overlay_catalog
from .lib.catalog.remote import (
	CHUNK_BYTES,
	FETCH_DEADLINE_SECONDS,
	FETCH_TIMEOUT,
	MAX_PAYLOAD_BYTES,
	loggable,
	parse_remote_payload,
	redact_url,
	validate_catalog_url,
)

_FETCH = "fetch"

# The first wait after a failed fetch, and the longest wait still performed
# (R5). Waits double: 1, 2, 4, 8, 16, 32 minutes, then retrying stops.
RETRY_FIRST_WAIT_MINUTES = 1
RETRY_MAX_WAIT_MINUTES = 32


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
			# raw.read1() returns as soon as one socket read delivers data
			# (b"" only at the end of the body), so the deadline is checked
			# after every read. iter_content() would not do: on a
			# Content-Length or close-delimited body each of its chunks waits
			# for CHUNK_BYTES bytes or EOF, so a server sending one byte every
			# few seconds never trips the deadline and holds this thread for
			# as long as it likes. decode_content matches iter_content().
			read1 = response.raw.read1
			chunks = []
			total = 0
			while True:
				chunk = read1(CHUNK_BYTES, decode_content=True)
				if not chunk:
					break
				total += len(chunk)
				if total > MAX_PAYLOAD_BYTES:
					return _failed("remote_too_large", f"limit {MAX_PAYLOAD_BYTES}")
				chunks.append(chunk)
				if past_deadline():
					return _failed("remote_timeout", f"deadline {FETCH_DEADLINE_SECONDS}s")
			return FetchResult(body=b"".join(chunks), issue=None)
	except Exception as error:  # noqa: BLE001
		return _failed("remote_request_failed", type(error).__name__)


THREAD_NAME = "wordbridge-catalog-fetch"
SOURCE_NONE, SOURCE_BUNDLED, SOURCE_CACHE, SOURCE_FETCHED = "none", "bundled", "cache", "fetched"
FETCH_OFF, FETCH_INVALID, FETCH_RUNNING, FETCH_SUCCEEDED, FETCH_FAILED = (
	"off", "invalid", "running", "succeeded", "failed",
)


@dataclass(frozen=True)
class UpdaterStatus:
	"""source: where the live local channel came from: none (no local
	models at all), bundled (the add-on's release-time model list), cache or
	fetched.
	fetch: off (empty URL), invalid (URL fails validation), running,
	succeeded or failed. Shown by the settings panel's status line.
	"""

	source: str
	fetch: str


@dataclass(frozen=True)
class CatalogChange:
	"""What a listener is told after a state change (spec section 9).

	catalog_changed: the live catalog was replaced. outcome: "succeeded" or
	"failed" for a finished fetch, else None (a fetch start). user_initiated:
	the finished fetch was started by the panel-open retry or a URL change,
	the only failures the settings panel speaks (R8).
	"""

	catalog_changed: bool
	outcome: str | None
	user_initiated: bool = False


@dataclass(frozen=True)
class ProbeResult:
	"""The outcome of testing a model list URL without installing it (spec 20.3).

	kind: ok, invalid, insecure_scheme, empty, network, http_status,
	not_a_list, no_models, failed, or unavailable (no updater installed).
	detail: the issue detail (the HTTP status for http_status), never shown
	in the log. models: selectable local items.
	"""

	kind: str
	detail: str = ""
	models: int = 0


_PROBE_NETWORK_CODES = frozenset({"remote_request_failed", "remote_timeout"})


def _probe_failure(issue) -> ProbeResult:
	if issue.code in _PROBE_NETWORK_CODES:
		return ProbeResult("network", issue.detail)
	if issue.code == "remote_http_status":
		return ProbeResult("http_status", issue.detail)
	if issue.code.startswith("remote_"):
		return ProbeResult("not_a_list", issue.detail)
	return ProbeResult("failed", issue.code)


def start_daemon_thread(target, args):
	thread = threading.Thread(target=target, args=args, name=THREAD_NAME, daemon=True)
	thread.start()
	return thread


def _fetch_state(check) -> str:
	if check.error is not None:
		return FETCH_INVALID
	return FETCH_RUNNING if check.enabled else FETCH_OFF


class CatalogUpdater:
	"""Keeps the live catalog in step with the configured URL.

	Threads: initial_catalog(), refresh() and _apply() run on the wx main
	thread; _run() runs on a daemon thread per fetch. Every fetch carries a
	generation; only the newest one, and only before shutdown, may write the
	cache or post a catalog, so a stale or abandoned thread can do no harm.
	The live catalog itself is only ever swapped on the main thread, through
	the injected install().

	After a failed fetch a retry is armed through the injected
	schedule(delay_ms, callback) (wx.CallLater in production), so the timer,
	its callback and all retry state live on the main thread too and need no
	lock. At most one timer exists: every fetch start cancels it, and only a
	failure arms it.
	"""

	def __init__(
		self,
		*,
		bundled_source,
		cache,
		runnable_providers,
		http_get,
		post_to_ui,
		install,
		shutdown,
		log,
		clock=time.monotonic,
		start_thread=start_daemon_thread,
		schedule=None,
	):
		self._bundled_source = bundled_source
		self._cache = cache
		self._runnable_providers = runnable_providers
		self._http_get = http_get
		self._post_to_ui = post_to_ui
		self._install = install
		self._shutdown = shutdown
		self._log = log
		self._clock = clock
		self._start_thread = start_thread
		self._lock = threading.Lock()
		self._generation = 0
		self._live_key = None
		self._source = SOURCE_NONE
		self._fetch = FETCH_OFF
		self._thread = None
		self._logged_invalid = set()
		# Retry state: main thread only (spec section 7.2).
		self._schedule = schedule
		self._retry_count = 0
		self._retries_stopped = False
		self._retry_timer = None
		self._current_url = ""
		self._user_initiated = False
		self._closed = False
		self._listeners = []

	@property
	def thread(self):
		return self._thread

	def status(self) -> UpdaterStatus:
		with self._lock:
			return UpdaterStatus(source=self._source, fetch=self._fetch)

	def initial_catalog(self, url: str):
		"""The cache for this URL if accepted, else the bundled models. Main thread."""
		check = self._check(url)
		self._current_url = url
		catalog, source = self._local_catalog(check)
		with self._lock:
			self._live_key = check.key
			self._source = source
			self._fetch = _fetch_state(check)
		self._log_source(check, source)
		return catalog

	def refresh(self, url: str, *, user_initiated=None) -> None:
		"""Fetch for `url`; on a URL change, switch to its cache at once (D8). Main thread.

		Cancels a pending retry. A URL change (a different key, including an
		empty or invalid URL) also resets the retry schedule (R10); a refresh
		with the same key (startup, a retry) keeps it. The fetch's outcome is
		user-initiated (R8) for a URL change, or as `user_initiated` says.
		"""
		check = self._check(url)
		self._cancel_retry_timer()
		self._current_url = url
		with self._lock:
			self._generation += 1
			generation = self._generation
			changed = check.key != self._live_key
			self._fetch = _fetch_state(check)
		if changed:
			self._retry_count = 0
			self._retries_stopped = False
			catalog, source = self._local_catalog(check)
			with self._lock:
				self._live_key = check.key
				self._source = source
			self._log_source(check, source)
			self._install(catalog)
		# Before the thread starts: its result may be applied at once.
		self._user_initiated = changed if user_initiated is None else user_initiated
		started = True
		if check.enabled:
			try:
				self._thread = self._start_thread(self._run, (generation, check))
			except Exception as error:  # noqa: BLE001
				# Thread.start() raises when no thread can be started. Left
				# "running", nothing would ever retry (fix review N2).
				self._log.warning("WordBridge: catalog fetch could not start type=%s", type(error).__name__)
				started = False
		self._notify(CatalogChange(catalog_changed=changed, outcome=None))
		if not started:
			self._fail_current(generation)

	def _fail_current(self, generation) -> None:
		"""Main thread: record a failure of `generation` that never reached
		_apply, then retry and notify as _apply does for a failed fetch."""
		with self._lock:
			if generation != self._generation:
				return
			self._fetch = FETCH_FAILED
		self._schedule_retry()
		self._notify(CatalogChange(catalog_changed=False, outcome=FETCH_FAILED, user_initiated=self._user_initiated))

	def retry_on_panel_open(self) -> bool:
		"""Main thread. Fetch now when the last fetch failed (R1, spec section 8).

		A pending retry is cancelled by refresh(), and a failure of this fetch
		continues the retry schedule (R6). Any other state starts nothing, so
		two fetches never overlap.
		"""
		if self._closed or self._shutdown.is_set():
			return False
		with self._lock:
			if self._fetch != FETCH_FAILED:
				return False
		self._log.info(
			"WordBridge: catalog fetch started on settings panel open host=%s",
			redact_url(validate_catalog_url(self._current_url).url),
		)
		self.refresh(self._current_url, user_initiated=True)
		return True

	def add_listener(self, listener) -> None:
		"""Main thread. `listener(change)` is called after every state change."""
		self._listeners.append(listener)

	def remove_listener(self, listener) -> None:
		"""Main thread. Removes an equal listener (a fresh bound method of the
		same object counts); an unknown one is ignored."""
		for index, known in enumerate(self._listeners):
			if known == listener:
				del self._listeners[index]
				return

	def close(self) -> None:
		"""Main thread; idempotent and never raises. Stops the retry timer and
		drops every listener (plugin terminate, spec section 14)."""
		self._closed = True
		self._listeners = []
		try:
			self._cancel_retry_timer()
		except Exception:  # noqa: BLE001, S110
			pass

	def _notify(self, change) -> None:
		for listener in list(self._listeners):
			try:
				listener(change)
			except Exception as error:  # noqa: BLE001
				self._log.warning("WordBridge: catalog listener failed type=%s", type(error).__name__)

	def probe(self, url: str) -> ProbeResult:
		"""Fetch, parse and accept `url` the way a refresh would, but install,
		cache, log and change nothing (the URL dialog's Test, C16). Safe on
		any thread; never raises."""
		try:
			return self._probe(url)
		except Exception as error:  # noqa: BLE001
			return ProbeResult("failed", type(error).__name__)

	def _probe(self, url) -> ProbeResult:
		check = validate_catalog_url(url)
		if check.error is not None:
			return ProbeResult(check.error)
		if not check.enabled:
			return ProbeResult("empty")
		result = fetch_payload(check.url, http_get=self._http_get, clock=self._clock)
		if result.issue is not None:
			return _probe_failure(result.issue)
		document, issues = parse_remote_payload(result.body)
		if document is None:
			return _probe_failure(issues[0])
		catalog, issues = accept_remote_document(
			self._bundled_source, document, runnable_providers=self._runnable_providers,
		)
		if catalog is not None:
			models = sum(len(catalog.items_for(group)) for group in catalog.provider_groups if group != COSEEING_GROUP)
			return ProbeResult("ok", models=models)
		# Explicit: _probe_failure() would map remote_no_models, like every
		# other remote_* code, to not_a_list.
		if issues[0].code == "remote_no_models":
			return ProbeResult("no_models")
		return _probe_failure(issues[0])

	def _cancel_retry_timer(self) -> None:
		timer, self._retry_timer = self._retry_timer, None
		if timer is not None:
			timer.Stop()

	def _schedule_retry(self) -> None:
		"""Main thread, after a failure of the current generation (spec section 7.2)."""
		if self._closed or self._shutdown.is_set() or self._schedule is None:
			return
		wait = RETRY_FIRST_WAIT_MINUTES * 2 ** self._retry_count
		if wait > RETRY_MAX_WAIT_MINUTES:
			if not self._retries_stopped:
				self._retries_stopped = True
				self._log.info("WordBridge: catalog fetch retries stopped attempts=%d", self._retry_count)
			return
		with self._lock:
			generation = self._generation
		# wx.CallLater raises once the wx app is gone. The caller still
		# notifies the failure, and a retry never armed does not count.
		try:
			timer = self._schedule(wait * 60_000, functools.partial(self._on_retry_timer, generation))
		except Exception as error:  # noqa: BLE001
			self._log.warning("WordBridge: catalog fetch retry could not be scheduled type=%s", type(error).__name__)
			return
		self._retry_count += 1
		self._retry_timer = timer
		self._log.info("WordBridge: catalog fetch retry scheduled attempt=%d delay=%dmin", self._retry_count, wait)

	def _on_retry_timer(self, armed_generation) -> None:
		"""Main thread. wx can deliver a timer after Stop(), so a stale or
		post-shutdown delivery, or one while a fetch runs, does nothing."""
		if self._closed or self._shutdown.is_set():
			return
		with self._lock:
			current = armed_generation == self._generation and self._fetch == FETCH_FAILED
		if not current:
			return
		self._retry_timer = None
		self.refresh(self._current_url)

	def _check(self, url):
		check = validate_catalog_url(url)
		if check.error is not None and check.url not in self._logged_invalid:
			self._logged_invalid.add(check.url)
			self._log.warning(
				"WordBridge: catalog URL is invalid code=%s; the remote catalog is off",
				check.error,
			)
		return check

	def _local_catalog(self, check) -> tuple:
		"""(catalog, source) from the cache when enabled and accepted, else the
		bundled file with its release-time models."""
		if check.enabled:
			document, issues = self._cache.load(check.key)
			self._log_cache_problems(issues)
			if document is not None:
				catalog, issues = accept_remote_document(
					self._bundled_source, document, runnable_providers=self._runnable_providers,
				)
				if catalog is not None:
					return catalog, SOURCE_CACHE
				# Spec section 10: a cached payload failing acceptance is an
				# unreadable cache; the acceptance code is its type.
				self._log_cache_problems(
					CatalogIssue("unreadable_cache", issue.location, issue.code) for issue in issues
				)
		catalog = load_overlay_catalog(self._bundled_source, None, runnable_providers=self._runnable_providers)
		return catalog, SOURCE_BUNDLED if has_local_items(catalog) else SOURCE_NONE

	def _log_source(self, check, source) -> None:
		"""Which catalog is in use, so a reader of the log can tell whether the
		cache was used (spec section 17.6, items 6 and 7)."""
		self._log.info(
			"WordBridge: catalog source=%s fetch=%s host=%s",
			source, _fetch_state(check), redact_url(check.url) if check.enabled else "(none)",
		)

	def _log_cache_problems(self, issues) -> None:
		for issue in issues:
			self._log.warning("WordBridge: catalog cache problem code=%s type=%s", issue.code, loggable(issue.detail))

	def _is_current(self, generation) -> bool:
		with self._lock:
			return not self._shutdown.is_set() and generation == self._generation

	def _fetch_and_build(self, check) -> tuple:
		"""(catalog, document, issue, size): fetch, parse and accept on this thread.

		build_catalog() is pure, so the catalog is built here and the main
		thread only swaps a reference.
		"""
		result = fetch_payload(check.url, http_get=self._http_get, clock=self._clock)
		if result.issue is not None:
			return None, None, result.issue, 0
		size = len(result.body)
		document, issues = parse_remote_payload(result.body)
		if document is None:
			return None, None, issues[0], size
		catalog, issues = accept_remote_document(
			self._bundled_source, document, runnable_providers=self._runnable_providers,
		)
		if catalog is None:
			return None, None, issues[0], size
		return catalog, document, None, size

	def _run(self, generation, check) -> None:
		"""The fetch thread. Never raises; a stale or post-shutdown result does nothing."""
		try:
			catalog, document, issue, size = self._fetch_and_build(check)
		except Exception as error:  # noqa: BLE001
			catalog, document, size = None, None, 0
			issue = CatalogIssue("remote_request_failed", _FETCH, type(error).__name__)
		if not self._is_current(generation):
			return
		if catalog is not None:
			# Outside the lock, so a slow disk never blocks the main thread. A
			# stale writer racing in between the check above and this write
			# stores its own url_key, so its file can never be used for the
			# wrong URL; the worst case is one more fetch at the next start.
			try:
				self._log_cache_problems(self._cache.store(check.key, document))
			except Exception as error:  # noqa: BLE001
				self._log.warning("WordBridge: catalog cache problem code=%s type=%s", "cache_write_failed", type(error).__name__)
		try:
			self._post_to_ui(self._apply, generation, check, catalog, issue, size)
		except Exception:  # noqa: BLE001, S110
			pass

	def _apply(self, generation, check, catalog, issue, size) -> None:
		"""Main thread: install a fetched catalog, or record the failure."""
		if not self._is_current(generation):
			return
		host = redact_url(check.url)
		if catalog is not None:
			self._install(catalog)
			with self._lock:
				self._live_key = check.key
				self._source = SOURCE_FETCHED
				self._fetch = FETCH_SUCCEEDED
			self._log.info(
				"WordBridge: catalog fetched host=%s bytes=%d models=%d",
				host, size, len(catalog.models),
			)
			self._retry_count = 0
			self._retries_stopped = False
			self._cancel_retry_timer()
			self._notify(CatalogChange(catalog_changed=True, outcome=FETCH_SUCCEEDED, user_initiated=self._user_initiated))
			return
		with self._lock:
			self._fetch = FETCH_FAILED
		self._log.warning(
			"WordBridge: catalog fetch failed host=%s code=%s type=%s",
			host, issue.code, loggable(issue.detail),
		)
		self._schedule_retry()
		self._notify(CatalogChange(catalog_changed=False, outcome=FETCH_FAILED, user_initiated=self._user_initiated))


_UPDATER = None


def install(updater) -> None:
	"""Make `updater` the one the settings panel talks to. Called by GlobalPlugin.__init__."""
	global _UPDATER
	_UPDATER = updater


def uninstall() -> None:
	"""Close the installed updater (timer, listeners) and drop it. Never raises."""
	global _UPDATER
	updater, _UPDATER = _UPDATER, None
	if updater is not None:
		try:
			updater.close()
		except Exception:  # noqa: BLE001, S110
			pass


def request_refresh(url: str) -> None:
	"""Main thread. A no-op when no updater is installed (plugin not running)."""
	updater = _UPDATER
	if updater is not None:
		updater.refresh(url)


def add_listener(listener) -> None:
	"""Main thread. A no-op when no updater is installed."""
	updater = _UPDATER
	if updater is not None:
		updater.add_listener(listener)


def remove_listener(listener) -> None:
	"""Main thread. A no-op when no updater is installed."""
	updater = _UPDATER
	if updater is not None:
		updater.remove_listener(listener)


def retry_on_panel_open() -> bool:
	"""Main thread. False when no updater is installed (plugin not running)."""
	updater = _UPDATER
	return updater.retry_on_panel_open() if updater is not None else False


def probe_url(url: str) -> ProbeResult:
	"""Any thread. ProbeResult("unavailable") when no updater is installed."""
	updater = _UPDATER
	return updater.probe(url) if updater is not None else ProbeResult("unavailable")


def status():
	"""The installed updater's UpdaterStatus, or None."""
	updater = _UPDATER
	return updater.status() if updater is not None else None
