from lib.progress_cue import ProgressCue


class FakeTimer:
	"""Stand-in for the object wx.CallLater returns."""

	def __init__(self, scheduler, delay_ms, callback):
		self.scheduler = scheduler
		self.delay_ms = delay_ms
		self.callback = callback
		self.stopped = False

	def Stop(self):
		self.stopped = True

	def fire(self):
		"""Deliver the timer the way wx's event loop would."""
		self.scheduler.fired.append(self.delay_ms)
		self.callback()


class FakeScheduler:
	"""Records wx.CallLater(delay_ms, callback) calls without an event loop."""

	def __init__(self):
		self.timers = []
		self.fired = []

	def __call__(self, delay_ms, callback):
		timer = FakeTimer(self, delay_ms, callback)
		self.timers.append(timer)
		return timer

	@property
	def pending(self):
		return self.timers[-1]


def _cue(scheduler, ticks, **kwargs):
	return ProgressCue(
		schedule=scheduler,
		tick=lambda: ticks.append(1),
		interval_ms=2000,
		**kwargs,
	)


def test_zero_initial_delay_ticks_before_the_first_timer():
	scheduler, ticks = FakeScheduler(), []
	cue = _cue(scheduler, ticks, initial_delay_ms=0)

	cue.start()

	assert ticks == [1]
	assert scheduler.pending.delay_ms == 2000


def test_nonzero_initial_delay_waits_for_the_first_timer():
	scheduler, ticks = FakeScheduler(), []
	cue = _cue(scheduler, ticks, initial_delay_ms=1000)

	cue.start()

	assert ticks == []
	assert scheduler.pending.delay_ms == 1000


def test_each_delivered_tick_rearms_at_the_interval():
	scheduler, ticks = FakeScheduler(), []
	cue = _cue(scheduler, ticks, initial_delay_ms=1000)
	cue.start()

	scheduler.pending.fire()
	scheduler.pending.fire()

	assert ticks == [1, 1]
	assert [timer.delay_ms for timer in scheduler.timers] == [1000, 2000, 2000]


def test_stop_cancels_the_pending_timer():
	scheduler, ticks = FakeScheduler(), []
	cue = _cue(scheduler, ticks, initial_delay_ms=1000)
	cue.start()
	timer = scheduler.pending

	cue.stop()

	assert timer.stopped


def test_a_tick_delivered_after_stop_neither_ticks_nor_rearms():
	scheduler, ticks = FakeScheduler(), []
	cue = _cue(scheduler, ticks, initial_delay_ms=1000)
	cue.start()
	timer = scheduler.pending
	cue.stop()

	timer.fire()

	assert ticks == []
	assert len(scheduler.timers) == 1


def test_starting_an_already_running_cue_does_not_arm_a_second_timer():
	scheduler, ticks = FakeScheduler(), []
	cue = _cue(scheduler, ticks, initial_delay_ms=1000)
	cue.start()

	cue.start()

	assert len(scheduler.timers) == 1


def test_stop_is_safe_before_start_and_twice():
	scheduler, ticks = FakeScheduler(), []
	cue = _cue(scheduler, ticks, initial_delay_ms=1000)

	cue.stop()
	cue.start()
	cue.stop()
	cue.stop()

	assert scheduler.timers[0].stopped
