class ProgressCue:
	"""A repeating audible cue that owns no thread of its own.

	Every tick re-arms itself through the injected scheduler, so binding
	`schedule` to `wx.CallLater` keeps the whole cue -- including the wave
	playback and the beep -- on the UI thread. That is the point: the cue this
	replaces ran in a background thread that polled the correction worker with
	`time.sleep()`, which `terminate()` neither tracked nor could interrupt.

	`schedule(delay_ms, callback)` must return an object with a `Stop()`
	method, which is exactly what `wx.CallLater` returns.

	`initial_delay_ms` of 0 ticks synchronously inside `start()`; any other
	value waits for the first timer. `None` means "use `interval_ms`".
	"""

	def __init__(self, *, schedule, tick, interval_ms: int, initial_delay_ms: int | None = None):
		self._schedule = schedule
		self._tick = tick
		self._interval_ms = interval_ms
		self._initial_delay_ms = interval_ms if initial_delay_ms is None else initial_delay_ms
		self._timer = None
		self._running = False

	def start(self):
		if self._running:
			return
		self._running = True
		if self._initial_delay_ms == 0:
			self._tick()
		self._arm(self._interval_ms if self._initial_delay_ms == 0 else self._initial_delay_ms)

	def stop(self):
		self._running = False
		timer, self._timer = self._timer, None
		if timer is not None:
			timer.Stop()

	def _arm(self, delay_ms: int):
		self._timer = self._schedule(delay_ms, self._on_timer)

	def _on_timer(self):
		# A timer can still be delivered after stop() -- wx queues the event
		# before Stop() is reached. Without this guard the cue would tick once
		# more and re-arm itself, outliving the task it reports on.
		if not self._running:
			return
		self._timer = None
		self._tick()
		if self._running:
			self._arm(self._interval_ms)
