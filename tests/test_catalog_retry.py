"""The updater's background retry, panel-open retry, listeners and URL probe
(docs/superpowers/specs/2026-11-04-catalog-retry-design.md sections 7-9, 20.3).

The fake scheduler stands in for wx.CallLater. It refuses to arm a timer while
another one is still live, so every test here also checks "at most one retry
timer exists".
"""

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


def exhaust(h):
	"""Fire every retry until none is armed; the delays in milliseconds."""
	delays = []
	while h.scheduler.live():
		delays.append(h.scheduler.live()[0].delay_ms)
		fire_and_finish(h)
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
	"all-providers-disallowed": lambda h, mp: _ok(_payload(url="https://evil.test/v1")),
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


def _two_providers_one_disallowed():
	payload = _payload("gpt-ok")
	payload["providers"]["DeepSeek"] = {
		"label": "DeepSeek", "url": "https://evil.test/v1", "setting": {}, "timeout0": 10, "timeout_max": 60,
	}
	payload["models"].append({"model": "ds", "provider": "DeepSeek", "label": "ds", "active": True})
	return payload


def _with_cache(cache_class):
	def setup(h):
		h.updater._cache = h.cache = cache_class(h.cache.inner)
		h.responses[URL_A] = _ok(_payload("fresh"))
		start(h)
	return setup


def _stale(h):
	h.responses[URL_A] = failing()
	h.updater.initial_catalog(URL_A)
	h.updater.refresh(URL_A)
	h.updater.refresh(URL_A)
	h.threads[0].run()
	h.deliver()


def _after_shutdown(h):
	h.responses[URL_A] = failing()
	h.updater.initial_catalog(URL_A)
	h.updater.refresh(URL_A)
	h.threads[0].run()
	h.shutdown.set()
	h.deliver()


def _dropped_provider(h):
	h.responses[URL_A] = _ok(_two_providers_one_disallowed())
	start(h)
	assert h.status() == ("fetched", "succeeded")


NOT_FAILURE_ROWS = {
	"dropped-provider": _dropped_provider,
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
