import pytest

from plugin_modules import load_plugin_module


updater = load_plugin_module("catalog_updater")
URL = "https://h.test/"
LIMIT = 1_048_576
CHUNK = 65536


class FakeRaw:
	"""urllib3's HTTPResponse as requests exposes it on response.raw.

	read1() returns what one socket read delivered -- here, the next chunk --
	and b"" at the end of the body, which is what lets the fetch check its
	deadline after every read however slowly a server sends.
	"""

	def __init__(self, response):
		self.response = response

	def read1(self, amt, decode_content=False):
		response = self.response
		response.iterated = True
		response.chunk_sizes.append(amt)
		response.decode_flags.append(decode_content)
		index = response.consumed
		if index >= len(response.chunks):
			return b""
		if response.raise_on_iter is not None and index == 1:
			raise response.raise_on_iter
		if index in response.tick_at:
			response.clock.now += response.tick_at[index]
		if response.drip_seconds:
			response.clock.now += response.drip_seconds
		response.consumed += 1
		return response.chunks[index]


class FakeResponse:
	def __init__(self, status_code=200, headers=None, chunks=(), raise_on_iter=None, clock=None, tick_at=None, drip_seconds=0):
		self.status_code = status_code
		self.headers = headers if headers is not None else {}
		self.chunks = list(chunks)
		self.raise_on_iter = raise_on_iter
		self.clock = clock
		self.tick_at = tick_at or {}
		self.drip_seconds = drip_seconds
		self.closed = False
		self.iterated = False
		self.consumed = 0
		self.chunk_sizes = []
		self.decode_flags = []
		self.raw = FakeRaw(self)

	def __enter__(self):
		return self

	def __exit__(self, *exc):
		self.closed = True
		return False

	def iter_content(self, chunk_size):
		"""What requests' iter_content does on a Content-Length or
		close-delimited body: each item waits for chunk_size bytes or the end
		of the body, so a slow server's gaps add up inside one item.
		"""
		while True:
			buffered = b""
			while len(buffered) < chunk_size:
				piece = self.raw.read1(chunk_size - len(buffered), decode_content=True)
				if not piece:
					break
				buffered += piece
			if not buffered:
				return
			yield buffered


class FakeClock:
	def __init__(self):
		self.now = 100.0

	def __call__(self):
		return self.now


def _fetch(response, calls=None, clock=None):
	def http_get(*args, **kwargs):
		if calls is not None:
			calls.append((args, kwargs))
		return response

	return updater.fetch_payload(URL, http_get=http_get, clock=clock or FakeClock())


def test_the_call_uses_exactly_the_specified_arguments():
	calls = []

	_fetch(FakeResponse(chunks=[b"{}"]), calls)

	assert calls == [((URL,), {
		"stream": True,
		"timeout": (5, 10),
		"allow_redirects": False,
		"headers": {"Accept": "application/json"},
	})]


def test_status_200_returns_the_body():
	response = FakeResponse(chunks=[b"ab", b"cd"])

	result = _fetch(response)

	assert result.body == b"abcd"
	assert result.issue is None
	assert set(response.chunk_sizes) == {CHUNK}


@pytest.mark.parametrize("status", [301, 304, 404, 500])
def test_non_200_is_rejected_with_the_number(status):
	response = FakeResponse(status_code=status, chunks=[b"{}"])

	result = _fetch(response)

	assert result.body is None
	assert (result.issue.code, result.issue.location, result.issue.detail) == ("remote_http_status", "fetch", str(status))
	assert response.iterated is False


def test_content_length_over_the_limit_is_rejected_without_reading():
	response = FakeResponse(headers={"Content-Length": str(LIMIT + 1)}, chunks=[b"{}"])

	result = _fetch(response)

	assert result.body is None
	assert result.issue.code == "remote_too_large"
	assert response.iterated is False


def test_content_length_at_the_limit_is_read():
	response = FakeResponse(headers={"Content-Length": str(LIMIT)}, chunks=[b"{}"])

	assert _fetch(response).body == b"{}"


def test_a_streamed_body_over_the_limit_stops_at_the_first_chunk_past_it():
	response = FakeResponse(chunks=[b"a" * CHUNK] * 20)

	result = _fetch(response)

	assert result.body is None
	assert result.issue.code == "remote_too_large"
	# 16 full chunks are exactly the limit; the 17th is the first past it.
	assert response.consumed == 17


def test_a_streamed_body_of_exactly_the_limit_is_accepted():
	response = FakeResponse(chunks=[b"a" * CHUNK] * 16)

	assert len(_fetch(response).body) == LIMIT


def test_the_overall_deadline_gives_remote_timeout():
	clock = FakeClock()
	response = FakeResponse(chunks=[b"a", b"b", b"c"], clock=clock, tick_at={1: 21})

	result = _fetch(response, clock=clock)

	assert result.body is None
	assert (result.issue.code, result.issue.detail) == ("remote_timeout", "deadline 20s")
	assert response.consumed == 2


def test_a_slow_connect_counts_toward_the_deadline():
	clock = FakeClock()
	response = FakeResponse(chunks=[b"{}"])

	def http_get(*args, **kwargs):
		clock.now += 25
		return response

	result = updater.fetch_payload(URL, http_get=http_get, clock=clock)

	assert result.issue.code == "remote_timeout"
	assert response.closed is True
	assert response.iterated is False


def test_an_exception_from_http_get_gives_request_failed_with_the_type_only():
	def http_get(*args, **kwargs):
		raise ConnectionError("https://h.test/secret?token=x")

	result = updater.fetch_payload(URL, http_get=http_get, clock=FakeClock())

	assert result.body is None
	assert (result.issue.code, result.issue.detail) == ("remote_request_failed", "ConnectionError")


def test_an_exception_while_reading_gives_request_failed_and_closes():
	response = FakeResponse(chunks=[b"a", b"b"], raise_on_iter=TimeoutError("read timed out: https://h.test/x"))

	result = _fetch(response)

	assert (result.issue.code, result.issue.detail) == ("remote_request_failed", "TimeoutError")
	assert response.closed is True


@pytest.mark.parametrize("make", [
	lambda clock: FakeResponse(chunks=[b"{}"]),
	lambda clock: FakeResponse(status_code=404),
	lambda clock: FakeResponse(headers={"Content-Length": str(LIMIT + 1)}),
	lambda clock: FakeResponse(chunks=[b"a", b"b"], clock=clock, tick_at={1: 21}),
], ids=["ok", "status", "too-large-header", "timeout"])
def test_the_response_is_closed_in_every_case(make):
	clock = FakeClock()
	response = make(clock)

	_fetch(response, clock=clock)

	assert response.closed is True


@pytest.mark.parametrize("length", ["abc", "-1", ""])
def test_unusable_content_length_falls_back_to_the_streamed_limit(length):
	small = FakeResponse(headers={"Content-Length": length}, chunks=[b"{}"])
	assert _fetch(small).body == b"{}"

	big = FakeResponse(headers={"Content-Length": length}, chunks=[b"a" * CHUNK] * 20)
	result = _fetch(big)
	assert result.issue.code == "remote_too_large"
	assert big.consumed == 17


def test_an_empty_read_ends_the_body():
	# raw.read1() returns b"" only at the end of the body.
	response = FakeResponse(chunks=[b"{}", b"", b"never read"])

	assert _fetch(response).body == b"{}"
	assert response.consumed == 2  # the data, then the empty end-of-body read


@pytest.mark.parametrize("headers", [
	{"Content-Length": "100000"},
	{},
	{"Transfer-Encoding": "chunked"},
], ids=["content-length", "close-delimited", "chunked"])
def test_a_dripping_server_times_out_at_the_deadline(headers):
	# One byte per read, 0.4 s apart: every gap is far below the 10 s socket
	# read timeout, so only the overall deadline can stop it.
	clock = FakeClock()
	start = clock.now
	response = FakeResponse(headers=headers, chunks=[b"a"] * 100000, clock=clock, drip_seconds=0.4)

	result = _fetch(response, clock=clock)

	assert (result.issue.code, result.issue.detail) == ("remote_timeout", "deadline 20s")
	# The deadline is checked after every read: never more than one read
	# past it.
	assert clock.now - start <= 20 + 0.4
	assert response.closed is True


def test_reads_decode_content_like_iter_content():
	response = FakeResponse(chunks=[b"{}"])

	_fetch(response)

	assert response.decode_flags and all(response.decode_flags)
