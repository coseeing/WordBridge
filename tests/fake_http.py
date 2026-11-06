"""A stand-in for a streamed requests.Response serving a fixed body.

The catalog fetch reads response.raw.read1(n, decode_content=True) until it
returns b"", so that is what this provides. tests/test_catalog_fetch.py has
its own, more detailed fake for the fetch limits themselves.
"""


class FakeRaw:
	def __init__(self, body: bytes):
		self._body = body
		self._position = 0

	def read1(self, amt, decode_content=False):
		piece = self._body[self._position : self._position + amt]
		self._position += len(piece)
		return piece


class BodyResponse:
	def __init__(self, body: bytes = b"", status_code: int = 200, headers=None):
		self.status_code = status_code
		self.headers = {"Content-Length": str(len(body))} if headers is None else headers
		self.body = body
		self.raw = FakeRaw(body)
		self.closed = False

	def fresh(self) -> "BodyResponse":
		"""A new, unread response with the same status, headers and body."""
		return BodyResponse(self.body, status_code=self.status_code, headers=dict(self.headers))

	def __enter__(self):
		return self

	def __exit__(self, *exc):
		self.closed = True
		return False
