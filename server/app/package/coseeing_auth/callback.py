from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from http.server import BaseHTTPRequestHandler, HTTPServer as _HTTPServer
import socket
from threading import Lock, Thread
import time
from typing import Callable
from urllib.parse import urlsplit, urlunsplit


_REQUEST_DEADLINE = 1.0


class HTTPServer(_HTTPServer):
    allow_reuse_address = True

    def get_request(self):
        request, client_address = super().get_request()
        accepted_sockets = getattr(self, "_accepted_sockets", None)
        socket_lock = getattr(self, "_socket_lock", None)
        if accepted_sockets is not None and socket_lock is not None:
            with socket_lock:
                if getattr(self, "_closing", False):
                    _close_socket(request)
                else:
                    accepted_sockets.add(request)
                    self._request_deadlines[request] = time.monotonic() + _REQUEST_DEADLINE
        return request, client_address

    def finish_request(self, request, client_address):
        try:
            return super().finish_request(request, client_address)
        finally:
            accepted_sockets = getattr(self, "_accepted_sockets", None)
            socket_lock = getattr(self, "_socket_lock", None)
            if accepted_sockets is not None and socket_lock is not None:
                with socket_lock:
                    accepted_sockets.discard(request)
                    self._request_deadlines.pop(request, None)

    def handle_error(self, *_args) -> None:
        return


def _close_socket(connection: socket.socket) -> None:
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        connection.close()
    except OSError:
        pass


class _DeadlineReader:
    closed = False

    def __init__(self, connection: socket.socket, deadline: float):
        self._connection = connection
        self._deadline = deadline

    def readline(self, limit: int = -1) -> bytes:
        line = bytearray()
        while limit < 0 or len(line) < limit:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("callback request deadline exceeded")
            self._connection.settimeout(remaining)
            chunk = self._connection.recv(1)
            if not chunk:
                break
            line.extend(chunk)
            if chunk == b"\n":
                break
        return bytes(line)

    def close(self) -> None:
        self.closed = True


class CallbackTimeout(TimeoutError):
    pass


class CallbackCancelled(Exception):
    pass


class _CallbackHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, callback_path: str, complete: Callable[[str], None], **kwargs):
        self._callback_path = callback_path
        self._complete = complete
        super().__init__(*args, **kwargs)

    def setup(self) -> None:
        super().setup()
        deadline = self.server._request_deadlines.get(self.request)
        if deadline is not None:
            self.rfile.close()
            self.rfile = _DeadlineReader(self.connection, deadline)

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path != self._callback_path:
            self.send_response(404)
            self.end_headers()
            return

        self._complete(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Authentication response received. You can close this tab.")

    def log_message(self, *_args) -> None:
        return


class LoopbackCallbackReceiver:
    def __init__(self, redirect_uri: str):
        configured = urlsplit(redirect_uri)
        self._port = configured.port
        self._callback_path = configured.path
        self._server: HTTPServer | None = None
        self._thread: Thread | None = None
        self._target: Future[str] = Future()
        self._target_lock = Lock()
        self._socket_lock = Lock()
        self._accepted_sockets: set[socket.socket] = set()
        self._request_deadlines: dict[socket.socket, float] = {}
        self._close_lock = Lock()
        self._closed = False
        self._started = False

    def start(self) -> None:
        with self._close_lock:
            if self._closed:
                raise RuntimeError("callback receiver is closed")
            if self._started:
                return
            self._server = HTTPServer(
                ("127.0.0.1", self._port),
                lambda *args, **kwargs: _CallbackHandler(
                    *args,
                    callback_path=self._callback_path,
                    complete=self._complete_result,
                    **kwargs,
                ),
            )
            self._server._accepted_sockets = self._accepted_sockets
            self._server._request_deadlines = self._request_deadlines
            self._server._socket_lock = self._socket_lock
            self._server._closing = False
            self._started = True
            self._thread = Thread(target=self._serve, daemon=True)
            self._thread.start()

    def wait(self, timeout: float) -> str:
        try:
            return self._target.result(timeout=timeout)
        except FutureTimeoutError as error:
            raise CallbackTimeout() from error

    def cancel(self) -> None:
        with self._target_lock:
            if not self._target.done():
                self._target.set_exception(CallbackCancelled())
        self._wake_server()

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self.cancel()
            self._shutdown_accepted_sockets()
            if self._thread is not None:
                self._thread.join(timeout=1.0)
            if self._server is not None:
                self._server.server_close()

    def _serve(self) -> None:
        server = self._server
        if server is None:
            return
        while not self._target.done():
            server.handle_request()

    def _complete_result(self, target: str) -> None:
        with self._target_lock:
            if not self._target.done():
                self._target.set_result(target)

    def _shutdown_accepted_sockets(self) -> None:
        server = self._server
        if server is None:
            return
        with self._socket_lock:
            server._closing = True
            sockets = tuple(self._accepted_sockets)
            self._accepted_sockets.clear()
            self._request_deadlines.clear()
        for connection in sockets:
            _close_socket(connection)

    def _wake_server(self) -> None:
        server = self._server
        if server is None or not self._started:
            return
        try:
            with socket.create_connection(server.server_address, timeout=0.2) as connection:
                connection.sendall(b"GET /__callback_stop__ HTTP/1.0\r\n\r\n")
        except OSError:
            return


def rebuild_callback_url(redirect_uri: str, raw_target: str) -> str:
    configured = urlsplit(redirect_uri)
    received = urlsplit(raw_target)
    if received.path != configured.path:
        raise ValueError("callback path does not match configured redirect URI")
    return urlunsplit((
        configured.scheme,
        configured.netloc,
        received.path,
        received.query,
        "",
    ))


__all__ = ["LoopbackCallbackReceiver", "rebuild_callback_url"]
