"""The updater's background retry, panel-open retry, listeners and URL probe
(docs/superpowers/specs/2026-11-04-catalog-retry-design.md sections 7-9, 20.3).

The fake scheduler stands in for wx.CallLater. It refuses to arm a timer while
another one is still live, so every test here also checks "at most one retry
timer exists".
"""

import copy
import itertools

import pytest

from fake_http import BodyResponse
from test_catalog_updater import (
	URL_A,
	URL_B,
	FailingStoreCache,
	FakeResponse,
	Harness,
	RaisingStoreCache,
	_ok,
	_payload,
	remote_module,
	updater_module,
)


SCHEDULED = "WordBridge: catalog fetch retry scheduled attempt=%d delay=%dmin"
STOPPED = "WordBridge: catalog fetch retries stopped attempts=%d"
MINUTE_MS = 60_000


class FakeTimer:
	"""What wx.CallLater returns: Stop(), plus fire() to deliver it."""

	def __init__(self, delay_ms, callback):
		self.delay_ms = delay_ms
		self.callback = callback
		self.stopped = False
		self.fired = False

	def Stop(self):
		self.stopped = True

	def fire(self):
		"""Deliver the timer, also after Stop(): wx can queue the event first."""
		self.fired = True
		self.callback()

	@property
	def live(self):
		return not self.stopped and not self.fired


class FakeScheduler:
	def __init__(self):
		self.timers = []

	def __call__(self, delay_ms, callback):
		assert not self.live(), "a retry timer was armed while another one is still live"
		timer = FakeTimer(delay_ms, callback)
		self.timers.append(timer)
		return timer

	def live(self):
		return [timer for timer in self.timers if timer.live]


def retry_harness(tmp_path, responses=None):
	scheduler = FakeScheduler()
	h = Harness(tmp_path, responses, schedule=scheduler)
	h.scheduler = scheduler
	return h


def finish(h):
	"""Run the newest fetch thread and deliver what it posted."""
	h.threads[-1].run()
	h.deliver()


def start(h, url=URL_A):
	"""Startup: initial catalog, the startup fetch, and its outcome."""
	h.updater.initial_catalog(url)
	h.updater.refresh(url)
	finish(h)


def fire_and_finish(h):
	[timer] = h.scheduler.live()
	timer.fire()
	finish(h)


def exhaust(h, bound=10):
	"""Fire every retry until none is armed; the delays in milliseconds.

	Bounded, so a broken schedule fails instead of looping forever."""
	delays = []
	for _ in range(bound):
		if not h.scheduler.live():
			break
		delays.append(h.scheduler.live()[0].delay_ms)
		fire_and_finish(h)
	assert not h.scheduler.live(), f"still retrying after {bound} retries"
	return delays


def records(h, line):
	return [record for record in h.log.records if record[1] == line]


def failing():
	return FakeResponse(status_code=500)


# --- Task 1: the schedule (R5, C1-C3) ---------------------------------------

@pytest.mark.parametrize("maximum, expected", [
	(32, [1, 2, 4, 8, 16, 32]),
	(0, []),
	(1, [1]),
	(3, [1, 2]),
	(40, [1, 2, 4, 8, 16, 32]),
], ids=["max-32", "max-0", "max-1", "max-3", "max-40"])
def test_retry_schedule_table(tmp_path, monkeypatch, maximum, expected):
	monkeypatch.setattr(updater_module, "RETRY_MAX_WAIT_MINUTES", maximum)
	h = retry_harness(tmp_path, {URL_A: failing()})
	start(h)

	delays = exhaust(h)

	assert delays == [minutes * MINUTE_MS for minutes in expected]
	assert h.requests == [URL_A] * (1 + len(expected))
	for _ in range(2):
		h.updater.refresh(URL_A)
		finish(h)
	assert h.scheduler.live() == []
	assert records(h, STOPPED) == [("info", STOPPED, len(expected))]


def test_a_wait_equal_to_the_maximum_is_performed(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing()})
	start(h)
	for _ in range(5):
		fire_and_finish(h)

	[timer] = h.scheduler.live()
	assert timer.delay_ms == 32 * MINUTE_MS
	fire_and_finish(h)

	assert len(h.requests) == 7


@pytest.mark.parametrize("k", range(6), ids=[f"k{k}" for k in range(6)])
def test_a_success_resets_the_schedule(tmp_path, k):
	h = retry_harness(tmp_path, {URL_A: failing()})
	start(h)
	for _ in range(k):
		fire_and_finish(h)

	h.responses[URL_A] = _ok(_payload("fresh"))
	fire_and_finish(h)

	assert h.scheduler.live() == []
	assert h.status() == ("fetched", "succeeded")
	h.responses[URL_A] = failing()
	h.updater.refresh(URL_A)
	finish(h)
	assert [timer.delay_ms for timer in h.scheduler.live()] == [MINUTE_MS]


def test_a_success_after_retries_stopped_lets_the_next_schedule_log_its_stop(tmp_path):
	# Final review m4 (mutant U10): a success also resets "retries stopped",
	# so a later schedule that runs out says so again.
	h = retry_harness(tmp_path, {URL_A: failing()})
	start(h)
	exhaust(h)
	h.responses[URL_A] = _ok(_payload("fresh"))
	h.updater.refresh(URL_A)
	finish(h)

	h.responses[URL_A] = failing()
	h.updater.refresh(URL_A)
	finish(h)
	exhaust(h)

	assert records(h, STOPPED) == [("info", STOPPED, 6)] * 2


def _deadline_clock():
	values = itertools.chain([0], itertools.repeat(100))
	return lambda: next(values)


def _raise_in_build(monkeypatch):
	def broken(body):
		raise RuntimeError("payload https://a.test/catalog?token=secret-a")

	monkeypatch.setattr(updater_module, "parse_remote_payload", broken)


TOO_MANY = remote_module.MAX_PAYLOAD_BYTES + 1
FAILURE_ROWS = {
	"404": lambda h, mp: FakeResponse(status_code=404),
	"500": lambda h, mp: FakeResponse(status_code=500),
	"301": lambda h, mp: FakeResponse(status_code=301),
	"timeout": lambda h, mp: setattr(h.updater, "_clock", _deadline_clock()) or _ok(_payload()),
	"declared-too-large": lambda h, mp: BodyResponse(b"{}", headers={"Content-Length": str(TOO_MANY)}),
	"streamed-too-large": lambda h, mp: BodyResponse(b"x" * TOO_MANY, headers={}),
	"non-json": lambda h, mp: BodyResponse(b"<html>"),
	"schema-2": lambda h, mp: _ok(dict(_payload(), schema_version=2)),
	"no-models": lambda h, mp: _ok(_payload(active=False)),
	"only-unknown-providers": lambda h, mp: _ok(_payload(provider="Mistral")),
	"raised-exception": lambda h, mp: OSError("connect failed"),
	"build-exception": lambda h, mp: _raise_in_build(mp) or _ok(_payload()),
}


@pytest.mark.parametrize("row", list(FAILURE_ROWS))
def test_every_fetch_failure_arms_a_retry(tmp_path, monkeypatch, row):
	h = retry_harness(tmp_path)
	h.responses[URL_A] = FAILURE_ROWS[row](h, monkeypatch)

	start(h)

	assert h.status()[1] == "failed"
	assert [timer.delay_ms for timer in h.scheduler.live()] == [MINUTE_MS]


def _one_model_for_an_unknown_provider():
	payload = _payload("gpt-ok")
	payload["models"].append({"model": "m-large", "provider": "Mistral", "label": "M Large", "active": True})
	return payload


def _with_cache(cache_class):
	def setup(h):
		h.updater._cache = h.cache = cache_class(h.cache.inner)
		h.responses[URL_A] = _ok(_payload("fresh"))
		start(h)
	return setup


def _stale(h):
	# The fetch finishes and posts while it is still current; the user saves
	# another URL before the main loop delivers it, so only _apply's own
	# generation check can drop it.
	h.responses[URL_A] = failing()
	h.responses[URL_B] = failing()
	h.updater.initial_catalog(URL_A)
	h.updater.refresh(URL_A)
	h.threads[0].run()
	h.updater.refresh(URL_B)
	h.deliver()


def _after_shutdown(h):
	h.responses[URL_A] = failing()
	h.updater.initial_catalog(URL_A)
	h.updater.refresh(URL_A)
	h.threads[0].run()
	h.shutdown.set()
	h.deliver()


def _dropped_model(h):
	h.responses[URL_A] = _ok(_one_model_for_an_unknown_provider())
	start(h)
	assert h.status() == ("fetched", "succeeded")


NOT_FAILURE_ROWS = {
	"dropped-model": _dropped_model,
	"cache-write-raises": _with_cache(RaisingStoreCache),
	"cache-write-reports": _with_cache(FailingStoreCache),
	"stale": _stale,
	"after-shutdown": _after_shutdown,
}


@pytest.mark.parametrize("row", list(NOT_FAILURE_ROWS))
def test_outcomes_that_are_not_failures_arm_nothing(tmp_path, row):
	h = retry_harness(tmp_path)

	NOT_FAILURE_ROWS[row](h)

	assert h.scheduler.timers == []


def test_a_failure_with_a_cache_in_use_is_retried(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing()})
	h.seed_cache(URL_A, _payload("cached"))

	start(h)

	assert h.status() == ("cache", "failed")
	assert len(h.scheduler.live()) == 1


def test_every_fetch_start_cancels_the_pending_timer(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing()})
	start(h)
	[timer] = h.scheduler.live()

	h.updater.refresh(URL_A)

	assert timer.stopped is True
	assert h.scheduler.live() == []


def test_a_stopped_timer_delivered_late_starts_nothing(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing()})
	start(h)
	[first] = h.scheduler.live()
	h.updater.refresh(URL_A)
	finish(h)
	[second] = h.scheduler.live()
	threads, requests = len(h.threads), list(h.requests)

	# The current generation has failed too, so only the generation check
	# keeps this stale delivery from starting a second fetch.
	first.fire()

	assert len(h.threads) == threads
	assert h.requests == requests
	assert h.updater._retry_timer is second
	h.updater._cancel_retry_timer()
	assert second.stopped is True


def test_a_timer_firing_while_the_fetch_runs_starts_nothing(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing()})
	h.updater.initial_catalog(URL_A)
	h.updater.refresh(URL_A)

	h.updater._on_retry_timer(1)

	assert len(h.threads) == 1


def test_shutdown_stops_retries(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing()})
	start(h)
	[timer] = h.scheduler.live()

	h.shutdown.set()
	timer.fire()

	assert len(h.threads) == 1


def test_without_a_scheduler_nothing_is_retried(tmp_path):
	h = Harness(tmp_path, {URL_A: failing()})

	start(h)

	assert h.status() == ("none", "failed")
	assert records(h, SCHEDULED) == [] and records(h, STOPPED) == []


def test_retry_log_lines_carry_only_attempt_and_delay(tmp_path):
	h = retry_harness(tmp_path, {URL_A: OSError("connect failed for https://a.test/catalog?token=secret-a")})
	start(h)
	assert records(h, SCHEDULED) == [("info", SCHEDULED, 1, 1)]

	exhaust(h)

	assert records(h, SCHEDULED) == [("info", SCHEDULED, attempt, 2 ** (attempt - 1)) for attempt in range(1, 7)]
	assert records(h, STOPPED) == [("info", STOPPED, 6)]
	text = h.log.text()
	for secret in ("/catalog", "token", "secret", "connect"):
		assert secret not in text


# --- Task 2: URL changes reset the backoff (R10, C4) ------------------------

@pytest.mark.parametrize("path", ["a-b", "a-b-a"])
def test_a_retry_fetches_the_current_url_not_the_armed_one(tmp_path, path):
	h = retry_harness(tmp_path, {URL_A: failing(), URL_B: failing()})
	start(h)
	[armed] = h.scheduler.live()

	h.updater.refresh(URL_B)
	final = URL_B
	if path == "a-b-a":
		h.updater.refresh(URL_A)
		final = URL_A
	assert armed.stopped is True
	threads, requests = len(h.threads), list(h.requests)
	armed.fire()
	assert (len(h.threads), h.requests) == (threads, requests)

	finish(h)
	assert [timer.delay_ms for timer in h.scheduler.live()] == [MINUTE_MS]
	fire_and_finish(h)
	assert h.requests[-1] == final


def test_a_url_change_resets_the_schedule(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing(), URL_B: failing()})
	start(h)
	fire_and_finish(h)
	fire_and_finish(h)
	assert [timer.delay_ms for timer in h.scheduler.live()] == [4 * MINUTE_MS]

	h.updater.refresh(URL_B)
	finish(h)

	assert exhaust(h) == [minutes * MINUTE_MS for minutes in (1, 2, 4, 8, 16, 32)]


def test_a_url_change_after_retries_stopped_starts_the_full_schedule_again(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing(), URL_B: failing()})
	start(h)
	exhaust(h)
	assert len(records(h, STOPPED)) == 1

	h.updater.refresh(URL_B)
	finish(h)

	assert exhaust(h) == [minutes * MINUTE_MS for minutes in (1, 2, 4, 8, 16, 32)]
	assert len(records(h, STOPPED)) == 2


def test_a_same_key_refresh_keeps_the_count(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing(), "  " + URL_A + "  ": failing()})
	start(h)

	h.updater.refresh("  " + URL_A + "  ")
	finish(h)

	assert [timer.delay_ms for timer in h.scheduler.live()] == [2 * MINUTE_MS]


@pytest.mark.parametrize("value", ["", "http://example.com/"], ids=["empty", "invalid"])
def test_switching_to_an_empty_or_invalid_url_cancels_and_resets(tmp_path, value):
	h = retry_harness(tmp_path, {URL_A: failing(), URL_B: failing()})
	start(h)
	fire_and_finish(h)
	[armed] = h.scheduler.live()
	assert armed.delay_ms == 2 * MINUTE_MS
	threads = len(h.threads)

	h.updater.refresh(value)

	assert armed.stopped is True
	assert len(h.threads) == threads
	assert h.scheduler.live() == []
	h.updater.refresh(URL_B)
	finish(h)
	assert [timer.delay_ms for timer in h.scheduler.live()] == [MINUTE_MS]


# --- Task 3: panel-open retry (R1, R6, C5) ----------------------------------

PANEL_LINE = "WordBridge: catalog fetch started on settings panel open host=%s"


def _state_failed(h):
	start(h)


def _state_failed_with_timer(h):
	start(h)
	assert len(h.scheduler.live()) == 1


def _state_running(h):
	h.updater.initial_catalog(URL_A)
	h.updater.refresh(URL_A)


def _state_succeeded(h):
	h.responses[URL_A] = _ok(_payload("fresh"))
	start(h)


def _state_off(h):
	h.updater.initial_catalog("")


def _state_invalid(h):
	h.updater.initial_catalog("http://example.com/")


def _state_failed_then_shut_down(h):
	# Final review m4 (mutant U11): terminate() sets the shutdown event
	# before it closes the updater.
	start(h)
	h.shutdown.set()


PANEL_OPEN_ROWS = [
	("failed", _state_failed, True, 1),
	("failed-with-timer", _state_failed_with_timer, True, 1),
	("running", _state_running, False, 0),
	("succeeded", _state_succeeded, False, 0),
	("off", _state_off, False, 0),
	("invalid", _state_invalid, False, 0),
	("shut-down", _state_failed_then_shut_down, False, 0),
]


@pytest.mark.parametrize(
	"state, result, new_threads", [row[1:] for row in PANEL_OPEN_ROWS], ids=[row[0] for row in PANEL_OPEN_ROWS],
)
def test_retry_on_panel_open_conditions(tmp_path, state, result, new_threads):
	h = retry_harness(tmp_path, {URL_A: failing()})
	state(h)
	armed = h.scheduler.live()
	threads = len(h.threads)

	assert h.updater.retry_on_panel_open() is result

	assert len(h.threads) - threads == new_threads
	if result:
		assert all(timer.stopped for timer in armed)
		assert h.status()[1] == "running"


def test_a_panel_open_failure_continues_the_schedule(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing()})
	start(h)

	assert h.updater.retry_on_panel_open() is True
	finish(h)

	assert [timer.delay_ms for timer in h.scheduler.live()] == [2 * MINUTE_MS]


def test_a_panel_open_failure_after_retries_stopped_arms_nothing(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing()})
	start(h)
	exhaust(h)

	assert h.updater.retry_on_panel_open() is True
	finish(h)

	assert h.scheduler.live() == []
	assert len(records(h, STOPPED)) == 1


def test_retry_on_panel_open_never_starts_a_second_fetch(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing()})
	start(h)
	threads = len(h.threads)

	assert h.updater.retry_on_panel_open() is True
	assert h.updater.retry_on_panel_open() is False

	assert len(h.threads) == threads + 1


def test_the_panel_open_log_line_names_only_the_host(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing()})
	start(h)

	h.updater.retry_on_panel_open()

	assert records(h, PANEL_LINE) == [("info", PANEL_LINE, "https://a.test")]
	assert "token" not in h.log.text() and "/catalog" not in h.log.text()


@pytest.mark.parametrize("installed", [False, True], ids=["no-updater", "installed"])
def test_module_retry_on_panel_open(tmp_path, installed):
	# Not relying on earlier tests to leave no updater installed (final review m7).
	updater_module.uninstall()
	h = retry_harness(tmp_path, {URL_A: failing()})
	start(h)
	threads = len(h.threads)
	if installed:
		updater_module.install(h.updater)
	try:
		assert updater_module.retry_on_panel_open() is installed
	finally:
		updater_module.uninstall()

	assert len(h.threads) - threads == (1 if installed else 0)


# --- Task 4: change events, listeners and close (C6, C14, R8) --------------

def C(*args):
	return updater_module.CatalogChange(*args)


class Recorder:
	def __init__(self):
		self.events = []

	def __call__(self, change):
		self.events.append(change)


def _listen(h):
	recorder = Recorder()
	h.updater.add_listener(recorder)
	return recorder


def _event_refresh_same_key(h):
	h.updater.initial_catalog(URL_A)
	recorder = _listen(h)
	h.updater.refresh(URL_A)
	return recorder


def _event_refresh_new_key(h):
	h.updater.initial_catalog(URL_A)
	recorder = _listen(h)
	h.updater.refresh(URL_B)
	return recorder


def _event_refresh_empty(h):
	h.updater.initial_catalog(URL_A)
	recorder = _listen(h)
	h.updater.refresh("")
	return recorder


def _event_startup(response):
	def scenario(h):
		h.responses[URL_A] = response()
		h.updater.initial_catalog(URL_A)
		recorder = _listen(h)
		h.updater.refresh(URL_A)
		finish(h)
		return recorder
	return scenario


def _event_timer_failure(h):
	start(h)
	recorder = _listen(h)
	fire_and_finish(h)
	return recorder


def _event_panel_failure(h):
	start(h)
	recorder = _listen(h)
	h.updater.retry_on_panel_open()
	finish(h)
	return recorder


def _event_panel_then_timer_failure(h):
	start(h)
	recorder = _listen(h)
	h.updater.retry_on_panel_open()
	finish(h)
	fire_and_finish(h)
	return recorder


def _event_url_change_then_timer_failure(h):
	h.responses[URL_B] = failing()
	start(h)
	recorder = _listen(h)
	h.updater.refresh(URL_B)
	finish(h)
	fire_and_finish(h)
	return recorder


def _event_url_change(response):
	def scenario(h):
		h.responses[URL_B] = response()
		start(h)
		recorder = _listen(h)
		h.updater.refresh(URL_B)
		finish(h)
		return recorder
	return scenario


EVENT_ROWS = [
	("refresh-same-key", _event_refresh_same_key, [(False, None)]),
	("refresh-new-key", _event_refresh_new_key, [(True, None)]),
	("refresh-empty-url", _event_refresh_empty, [(True, None)]),
	("startup-success", _event_startup(lambda: _ok(_payload("fresh"))), [(False, None), (True, "succeeded", False)]),
	("startup-failure", _event_startup(failing), [(False, None), (False, "failed", False)]),
	("timer-failure", _event_timer_failure, [(False, None), (False, "failed", False)]),
	("panel-failure", _event_panel_failure, [(False, None), (False, "failed", True)]),
	("url-change-failure", _event_url_change(failing), [(True, None), (False, "failed", True)]),
	("url-change-success", _event_url_change(lambda: _ok(_payload("b"))), [(True, None), (True, "succeeded", True)]),
	# A timer retry after a user-initiated failure is a background retry again (R8).
	("panel-then-timer-failure", _event_panel_then_timer_failure,
		[(False, None), (False, "failed", True), (False, None), (False, "failed", False)]),
	("url-change-then-timer-failure", _event_url_change_then_timer_failure,
		[(True, None), (False, "failed", True), (False, None), (False, "failed", False)]),
]


@pytest.mark.parametrize("scenario, expected", [row[1:] for row in EVENT_ROWS], ids=[row[0] for row in EVENT_ROWS])
def test_change_events_table(tmp_path, scenario, expected):
	h = retry_harness(tmp_path, {URL_A: failing()})

	recorder = scenario(h)

	assert recorder.events == [C(*event) for event in expected]


def _synchronous(h):
	"""The fetch runs inside start_thread and its result is applied at once:
	nothing may depend on wx.CallAfter running later (final review m5)."""
	def start_thread(target, args):
		target(*args)

	h.updater._start_thread = start_thread
	h.updater._post_to_ui = lambda function, *args: function(*args)


def _sync_panel_open(h):
	h.updater.retry_on_panel_open()


def _sync_url_change(h):
	h.updater.refresh(URL_B)


def _sync_timer(h):
	[timer] = h.scheduler.live()
	timer.fire()


@pytest.mark.parametrize("action, user_initiated", [
	(_sync_panel_open, True),
	(_sync_url_change, True),
	(_sync_timer, False),
], ids=["panel-open", "url-change", "timer"])
def test_user_initiated_is_set_before_a_synchronous_fetch_completes(tmp_path, action, user_initiated):
	h = retry_harness(tmp_path, {URL_A: failing(), URL_B: failing()})
	start(h)
	_synchronous(h)
	recorder = _listen(h)

	action(h)

	assert [event for event in recorder.events if event.outcome is not None] == [C(False, "failed", user_initiated)]


@pytest.mark.parametrize("response, expected", [
	(lambda: _ok(_payload("fresh")), ("succeeded", ("fetched", "succeeded"), 1, 0)),
	(failing, ("failed", ("none", "failed"), 0, 1)),
], ids=["success", "failure"])
def test_listeners_see_the_new_state_when_notified(tmp_path, response, expected):
	h = retry_harness(tmp_path, {URL_A: response()})
	h.updater.initial_catalog(URL_A)
	seen = []

	def listener(change):
		status = h.updater.status()
		seen.append((change.outcome, (status.source, status.fetch), len(h.installed), len(h.scheduler.live())))

	h.updater.add_listener(listener)
	h.updater.refresh(URL_A)
	finish(h)

	assert seen[-1] == expected


@pytest.mark.parametrize("url, status", [
	(URL_B, ("cache", "running")),
	("", ("none", "off")),
], ids=["new-url-with-cache", "empty-url"])
def test_a_url_change_event_sees_the_d8_catalog_installed(tmp_path, url, status):
	# The panel rebuilds from registry.current() when told; the D8 switch must
	# already be installed, and an empty URL is never followed by a fetch.
	h = retry_harness(tmp_path, {URL_A: failing(), URL_B: failing()})
	h.seed_cache(URL_B, _payload("cached-b"))
	h.updater.initial_catalog(URL_A)
	seen = []
	h.updater.add_listener(lambda change: seen.append((change, len(h.installed), h.status())))

	h.updater.refresh(url)

	assert seen == [(C(True, None), 1, status)]


def test_a_raising_listener_is_logged_by_type_and_the_next_still_runs(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing()})
	h.updater.initial_catalog(URL_A)

	def broken(change):
		raise ValueError("secret detail")

	h.updater.add_listener(broken)
	recorder = _listen(h)
	h.updater.refresh(URL_A)

	assert recorder.events == [C(False, None)]
	assert ("warning", "WordBridge: catalog listener failed type=%s", "ValueError") in h.log.records
	assert "secret" not in h.log.text()


def test_remove_listener_accepts_an_equal_bound_method_and_ignores_unknown(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing()})
	h.updater.initial_catalog(URL_A)

	class Panel:
		def __init__(self):
			self.events = []

		def on_change(self, change):
			self.events.append(change)

	panel = Panel()
	h.updater.add_listener(panel.on_change)
	h.updater.remove_listener(panel.on_change)
	h.updater.remove_listener(lambda change: None)
	h.updater.refresh(URL_A)

	assert panel.events == []


def test_close_stops_the_timer_clears_listeners_and_is_idempotent(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing()})
	start(h)
	[armed] = h.scheduler.live()
	recorder = _listen(h)

	h.updater.close()
	h.updater.close()

	assert armed.stopped is True
	h.updater.refresh(URL_A)
	assert recorder.events == []


def test_after_close_nothing_is_armed_or_started(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing()})
	start(h)
	[armed] = h.scheduler.live()
	h.updater.close()
	threads = len(h.threads)

	# Same generation and still failed: only the closed check stops it.
	armed.fire()
	assert len(h.threads) == threads

	other = retry_harness(tmp_path, {URL_A: failing()})
	other.updater.initial_catalog(URL_A)
	other.updater.refresh(URL_A)
	other.threads[-1].run()
	other.updater.close()
	other.deliver()
	assert other.status() == ("none", "failed")
	assert other.scheduler.timers == []
	assert other.updater.retry_on_panel_open() is False


def test_close_never_raises_when_stop_raises(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing()})
	start(h)
	[armed] = h.scheduler.live()

	def broken():
		raise RuntimeError("wx is gone")

	armed.Stop = broken
	recorder = _listen(h)

	h.updater.close()

	h.updater.refresh(URL_A)
	assert recorder.events == []


SCHEDULE_FAILED = "WordBridge: catalog fetch retry could not be scheduled type=%s"
START_FAILED = "WordBridge: catalog fetch could not start type=%s"


def _raise_on_thread_start(h):
	def start_thread(target, args):
		raise RuntimeError("can't start new thread for https://a.test/catalog?token=secret-a")

	working, h.updater._start_thread = h.updater._start_thread, start_thread
	return working


def _start_fail_startup(h):
	h.updater.initial_catalog(URL_A)
	_raise_on_thread_start(h)
	recorder = _listen(h)
	h.updater.refresh(URL_A)
	return recorder


def _start_fail_url_change(h):
	start(h)
	_raise_on_thread_start(h)
	recorder = _listen(h)
	h.updater.refresh(URL_B)
	return recorder


def _start_fail_panel_open(h):
	start(h)
	_raise_on_thread_start(h)
	recorder = _listen(h)
	assert h.updater.retry_on_panel_open() is True
	return recorder


def _start_fail_timer(h):
	start(h)
	_raise_on_thread_start(h)
	recorder = _listen(h)
	[timer] = h.scheduler.live()
	timer.fire()
	return recorder


# (trigger, its two events, the next retry's delay in minutes): R8 speech
# follows the trigger, R10 restarts the count on a URL change, R6 continues it.
START_FAILURE_ROWS = [
	("startup", _start_fail_startup, [(False, None), (False, "failed", False)], 1),
	("url-change", _start_fail_url_change, [(True, None), (False, "failed", True)], 1),
	("panel-open", _start_fail_panel_open, [(False, None), (False, "failed", True)], 2),
	("timer", _start_fail_timer, [(False, None), (False, "failed", False)], 2),
]


@pytest.mark.parametrize(
	"trigger, events, delay", [row[1:] for row in START_FAILURE_ROWS], ids=[row[0] for row in START_FAILURE_ROWS],
)
def test_a_fetch_thread_that_cannot_start_is_a_failure(tmp_path, trigger, events, delay):
	# Fix review N2: Thread.start() raising left fetch=running with no timer,
	# so the panel said "still loading" and never retried.
	h = retry_harness(tmp_path, {URL_A: failing(), URL_B: failing()})

	recorder = trigger(h)

	assert h.status()[1] == "failed"
	assert recorder.events == [C(*event) for event in events]
	assert [timer.delay_ms for timer in h.scheduler.live()] == [delay * MINUTE_MS]
	assert records(h, START_FAILED) == [("warning", START_FAILED, "RuntimeError")]
	assert "secret" not in h.log.text()


def test_after_a_thread_start_failure_the_panel_open_retry_fetches(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing()})
	h.updater.initial_catalog(URL_A)
	working = _raise_on_thread_start(h)
	h.updater.refresh(URL_A)
	h.updater._start_thread = working
	threads = len(h.threads)

	assert h.updater.retry_on_panel_open() is True

	assert len(h.threads) == threads + 1
	assert h.status()[1] == "running"


def test_a_raising_scheduler_keeps_the_count_and_still_notifies(tmp_path):
	# Final review m2: wx.CallLater raises once the wx app is gone. The
	# failure must still reach the listeners, and the count must not grow
	# for a retry that was never armed.
	h = retry_harness(tmp_path, {URL_A: failing()})
	working = h.updater._schedule

	def broken(delay_ms, callback):
		raise RuntimeError("no wx app for https://a.test/catalog?token=secret-a")

	h.updater._schedule = broken
	h.updater.initial_catalog(URL_A)
	recorder = _listen(h)
	h.updater.refresh(URL_A)
	finish(h)

	assert recorder.events == [C(False, None), C(False, "failed", False)]
	assert records(h, SCHEDULE_FAILED) == [("warning", SCHEDULE_FAILED, "RuntimeError")]
	assert records(h, SCHEDULED) == []
	assert "secret" not in h.log.text()
	assert h.updater._retry_timer is None

	h.updater._schedule = working
	h.updater.refresh(URL_A)
	finish(h)
	assert [timer.delay_ms for timer in h.scheduler.live()] == [MINUTE_MS]
	assert records(h, SCHEDULED) == [("info", SCHEDULED, 1, 1)]


def test_module_listener_functions_without_an_updater_are_no_ops():
	updater_module.uninstall()

	updater_module.add_listener(print)
	updater_module.remove_listener(print)

	assert updater_module.status() is None


def test_uninstall_closes_the_installed_updater(tmp_path):
	h = retry_harness(tmp_path, {URL_A: failing()})
	start(h)
	[armed] = h.scheduler.live()
	updater_module.install(h.updater)

	updater_module.uninstall()

	assert armed.stopped is True
	assert updater_module.status() is None


# --- Task 5: the URL probe behind the dialog's "Test..." (C16) ------------

def P(*args, **kwargs):
	return updater_module.ProbeResult(*args, **kwargs)


def _raise_in_accept(monkeypatch):
	def broken(*args, **kwargs):
		raise RuntimeError("payload https://a.test/catalog?token=secret-a")

	monkeypatch.setattr(updater_module, "accept_remote_document", broken)


PROBE_ROWS = [
	# id, url, response(h, monkeypatch) or None (no request expected), kind, detail, models
	("ok", URL_A, lambda h, mp: _ok(_payload("fresh")), "ok", "", 1),
	("invalid", "ftp://x", None, "invalid", "", 0),
	("insecure", "http://example.com", None, "insecure_scheme", "", 0),
	("empty", "  ", None, "empty", "", 0),
	("network-raise", URL_A, lambda h, mp: OSError("connect failed"), "network", "OSError", 0),
	("network-timeout", URL_A, lambda h, mp: setattr(h.updater, "_clock", _deadline_clock()) or _ok(_payload()), "network", None, 0),
	("http-404", URL_A, lambda h, mp: FakeResponse(status_code=404), "http_status", "404", 0),
	("non-json", URL_A, lambda h, mp: BodyResponse(b"<html>"), "not_a_list", None, 0),
	("schema-2", URL_A, lambda h, mp: _ok(dict(_payload(), schema_version=2)), "not_a_list", None, 0),
	("too-large", URL_A, lambda h, mp: BodyResponse(b"{}", headers={"Content-Length": str(TOO_MANY)}), "not_a_list", None, 0),
	("hostile-providers-ignored", URL_A, lambda h, mp: _ok(_payload("fresh", url="https://evil.test/v1")), "ok", "", 1),
	("unknown-providers-only", URL_A, lambda h, mp: _ok(_payload(provider="Mistral")), "no_models", None, 0),
	("no-models", URL_A, lambda h, mp: _ok(_payload(active=False)), "no_models", None, 0),
	("build-exception", URL_A, lambda h, mp: _raise_in_accept(mp) or _ok(_payload()), "failed", "RuntimeError", 0),
]


@pytest.mark.parametrize("url, response, kind, detail, models", [row[1:] for row in PROBE_ROWS], ids=[row[0] for row in PROBE_ROWS])
def test_probe_result_table(tmp_path, monkeypatch, url, response, kind, detail, models):
	h = retry_harness(tmp_path)
	if response is not None:
		h.responses[url] = response(h, monkeypatch)

	result = h.updater.probe(url)

	assert (result.kind, result.models) == (kind, models)
	if detail is not None:
		assert result.detail == detail
	if response is None:
		assert h.requests == []


def test_probe_sends_the_d4_request(tmp_path):
	h = retry_harness(tmp_path)
	calls = []

	def http_get(url, **kwargs):
		calls.append((url, kwargs))
		return _ok(_payload("fresh")).fresh()

	h.updater._http_get = http_get

	h.updater.probe(URL_B)

	assert calls == [(URL_B, {
		"stream": True, "timeout": (5, 10), "allow_redirects": False, "headers": {"Accept": "application/json"},
	})]


def _updater_state(updater):
	return {
		key: copy.copy(value) if isinstance(value, (list, set, dict)) else value
		for key, value in vars(updater).items()
	}


def test_probe_installs_caches_and_changes_nothing(tmp_path):
	# A tested but unsaved URL must never become the URL a later retry fetches
	# or D8 switches to (C4, D8, C16).
	h = retry_harness(tmp_path, {URL_A: failing(), URL_B: _ok(_payload("b"))})
	start(h)
	[armed] = h.scheduler.live()
	recorder = _listen(h)
	before, records = _updater_state(h.updater), list(h.log.records)
	installed, stores, threads = list(h.installed), list(h.cache.stores), len(h.threads)

	assert h.updater.probe(URL_B).kind == "ok"
	for url in ("http://example.com/", "ftp://x", ""):
		h.updater.probe(url)

	assert _updater_state(h.updater) == before
	assert h.scheduler.live() == [armed]
	assert h.log.records == records
	assert (h.installed, h.cache.stores, len(h.threads), recorder.events) == (installed, stores, threads, [])


@pytest.mark.parametrize("installed", [False, True], ids=["no-updater", "installed"])
def test_module_probe_url(tmp_path, installed):
	# Not relying on earlier tests to leave no updater installed (final review m7).
	updater_module.uninstall()
	h = retry_harness(tmp_path, {URL_B: _ok(_payload("b"))})
	if installed:
		updater_module.install(h.updater)
	try:
		result = updater_module.probe_url(URL_B)
	finally:
		updater_module.uninstall()

	assert result.kind == ("ok" if installed else "unavailable")
	if not installed:
		assert result == P("unavailable")


def test_a_listener_removing_itself_does_not_skip_the_next(tmp_path):
	# The settings panel unregisters itself from inside a notification.
	h = retry_harness(tmp_path, {URL_A: failing()})
	h.updater.initial_catalog(URL_A)
	second = Recorder()

	def first(change):
		h.updater.remove_listener(first)

	h.updater.add_listener(first)
	h.updater.add_listener(second)
	h.updater.refresh(URL_A)

	assert second.events == [C(False, None)]
