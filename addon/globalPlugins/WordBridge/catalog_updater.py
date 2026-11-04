"""Fetches the remote catalog and keeps the live catalog up to date.

Imports only the standard library and .lib.catalog. NVDA's `requests`, wx,
config and the log are injected by __init__.py, so importing this module has
no side effects and tests never touch the network.
"""

from dataclasses import dataclass
import functools
import threading
import time

from .lib.catalog.model import CatalogIssue
from .lib.catalog.overlay import accept_remote_document, load_overlay_catalog
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
	except Exception as error:
		return _failed("remote_request_failed", type(error).__name__)


THREAD_NAME = "wordbridge-catalog-fetch"
SOURCE_NONE, SOURCE_CACHE, SOURCE_FETCHED = "none", "cache", "fetched"
FETCH_OFF, FETCH_INVALID, FETCH_RUNNING, FETCH_SUCCEEDED, FETCH_FAILED = (
	"off", "invalid", "running", "succeeded", "failed",
)


@dataclass(frozen=True)
class UpdaterStatus:
	"""source: where the live local channel came from (none, cache, fetched).
	fetch: off (empty URL), invalid (URL fails validation), running,
	succeeded or failed. Shown by the settings panel's status line.
	"""

	source: str
	fetch: str


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

	@property
	def thread(self):
		return self._thread

	def status(self) -> UpdaterStatus:
		with self._lock:
			return UpdaterStatus(source=self._source, fetch=self._fetch)

	def initial_catalog(self, url: str):
		"""Bundled ⊕ (cache for this URL, if accepted). Main thread."""
		check = self._check(url)
		self._current_url = url
		catalog, source = self._local_catalog(check)
		with self._lock:
			self._live_key = check.key
			self._source = source
			self._fetch = _fetch_state(check)
		self._log_source(check, source)
		return catalog

	def refresh(self, url: str) -> None:
		"""Fetch for `url`; on a URL change, switch to its cache at once (D8). Main thread."""
		check = self._check(url)
		self._cancel_retry_timer()
		self._current_url = url
		with self._lock:
			self._generation += 1
			generation = self._generation
			changed = check.key != self._live_key
			self._fetch = _fetch_state(check)
		if changed:
			catalog, source = self._local_catalog(check)
			with self._lock:
				self._live_key = check.key
				self._source = source
			self._log_source(check, source)
			self._install(catalog)
		if check.enabled:
			self._thread = self._start_thread(self._run, (generation, check))

	def _cancel_retry_timer(self) -> None:
		timer, self._retry_timer = self._retry_timer, None
		if timer is not None:
			timer.Stop()

	def _schedule_retry(self) -> None:
		"""Main thread, after a failure of the current generation (spec section 7.2)."""
		if self._shutdown.is_set() or self._schedule is None:
			return
		wait = RETRY_FIRST_WAIT_MINUTES * 2 ** self._retry_count
		if wait > RETRY_MAX_WAIT_MINUTES:
			if not self._retries_stopped:
				self._retries_stopped = True
				self._log.info("WordBridge: catalog fetch retries stopped attempts=%d", self._retry_count)
			return
		self._retry_count += 1
		with self._lock:
			generation = self._generation
		self._retry_timer = self._schedule(wait * 60_000, functools.partial(self._on_retry_timer, generation))
		self._log.info("WordBridge: catalog fetch retry scheduled attempt=%d delay=%dmin", self._retry_count, wait)

	def _on_retry_timer(self, armed_generation) -> None:
		"""Main thread. wx can deliver a timer after Stop(), so a stale or
		post-shutdown delivery, or one while a fetch runs, does nothing."""
		if self._shutdown.is_set():
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
		"""(catalog, source) from the bundled file and, when enabled, the cache."""
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
		return catalog, SOURCE_NONE

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
		except Exception as error:
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
			except Exception as error:
				self._log.warning("WordBridge: catalog cache problem code=%s type=%s", "cache_write_failed", type(error).__name__)
		try:
			self._post_to_ui(self._apply, generation, check, catalog, issue, size)
		except Exception:
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
			return
		with self._lock:
			self._fetch = FETCH_FAILED
		self._log.warning(
			"WordBridge: catalog fetch failed host=%s code=%s type=%s",
			host, issue.code, loggable(issue.detail),
		)
		self._schedule_retry()


_UPDATER = None


def install(updater) -> None:
	"""Make `updater` the one the settings panel talks to. Called by GlobalPlugin.__init__."""
	global _UPDATER
	_UPDATER = updater


def uninstall() -> None:
	global _UPDATER
	_UPDATER = None


def request_refresh(url: str) -> None:
	"""Main thread. A no-op when no updater is installed (plugin not running)."""
	updater = _UPDATER
	if updater is not None:
		updater.refresh(url)


def status():
	"""The installed updater's UpdaterStatus, or None."""
	updater = _UPDATER
	return updater.status() if updater is not None else None
