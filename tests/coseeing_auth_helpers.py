from collections import deque
from concurrent.futures import Future


class FakeAuth:
	def __init__(self):
		self.calls = []
		self.pending = deque()

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


class AuthHarness:
	def __init__(self, session_class, refresh=None, choice="guest", save_error=None):
		self.auth = FakeAuth()
		self.queue = deque()
		self.saved = refresh
		self.choice = choice
		self.save_error = save_error
		self.prompts = 0
		self.session = session_class(
			client_factory=lambda: self.auth,
			post_ui=lambda fn, *args: self.queue.append((fn, args)),
			read_refresh_token=lambda: self.saved,
			save_refresh_token=self.save,
			prompt_login=self.prompt,
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
		self.auth.pending.popleft().set_result(value)
		self.drain()

	def reject(self, error):
		self.auth.pending.popleft().set_exception(error)
		self.drain()
