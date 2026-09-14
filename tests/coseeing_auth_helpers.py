from collections import deque
from concurrent.futures import Future
from threading import Event, current_thread


class FakeAuth:
	def __init__(self, close_started=None, close_release=None):
		self.calls = []
		self.pending = deque()
		self.close_started = close_started
		self.close_release = close_release
		self.close_thread_name = None

	def _submit(self, name, *args, **kwargs):
		result = Future()
		self.calls.append((name, args, kwargs))
		self.pending.append(result)
		return result

	def restore(self, token):
		return self._submit("restore", token)

	def get_access_token(self, *, auto_login=False):
		return self._submit("get_access_token", auto_login=auto_login)

	def get_refresh_token(self):
		return self._submit("get_refresh_token")

	def login(self):
		return self._submit("login")

	def close(self):
		self.calls.append(("close", (), {}))
		self.close_thread_name = current_thread().name
		if self.close_started is not None:
			self.close_started.set()
		if self.close_release is not None:
			self.close_release.wait(timeout=5)


class AuthHarness:
	def __init__(self, session_class, refresh=None, choice="guest", save_error=None, close_blocked=False, auth_state=None):
		self.auth = None
		self.close_started = Event() if close_blocked else None
		self.close_release = Event() if close_blocked else None
		self.queue = deque()
		self.saved = refresh
		self.choice = choice
		self.save_error = save_error
		self.prompts = 0
		def make_auth():
			self.auth = FakeAuth(self.close_started, self.close_release)
			return self.auth

		self.session = session_class(
			client_factory=make_auth,
			post_ui=lambda fn, *args: self.queue.append((fn, args)),
			read_refresh_token=lambda: self.saved,
			save_refresh_token=self.save,
			prompt_login=self.prompt,
			auth_state=auth_state,
		)

	def save(self, value):
		if self.save_error is not None:
			raise self.save_error
		self.saved = value

	def prompt(self):
		self.prompts += 1
		return self.choice

	def drain(self):
		while self.queue:
			fn, args = self.queue.popleft()
			fn(*args)

	def resolve(self, value):
		assert self.auth is not None
		self.auth.pending.popleft().set_result(value)
		self.drain()

	def reject(self, error):
		assert self.auth is not None
		self.auth.pending.popleft().set_exception(error)
		self.drain()
