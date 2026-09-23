import threading
from concurrent.futures import Executor, Future, ThreadPoolExecutor

from .client import CoseeingAuthClient
from .errors import AuthError


class FutureAuthClient:
    """Future-based facade over a synchronous :class:`CoseeingAuthClient`."""

    def __init__(self, client: CoseeingAuthClient, executor: Executor | None = None) -> None:
        self._client = client
        self._executor = executor if executor is not None else ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="coseeing-auth",
        )
        self._owns_executor = executor is None
        self._lock = threading.RLock()
        self._closed = False
        self._futures: set[Future] = set()
        self._worker_context = threading.local()
        self._finalizer_started = False

    def _submit(self, operation: str, method, *args, **kwargs) -> Future:
        with self._lock:
            if self._closed:
                raise AuthError(
                    "authentication client is closed",
                    operation=operation,
                    stage="concurrency",
                    code="client_closed",
                    retryable=False,
                )
            future = self._executor.submit(self._execute, method, args, kwargs)
            self._futures.add(future)
            future.add_done_callback(self._discard_future)
            return future

    def _execute(self, method, args, kwargs):
        # Future callbacks run after the executor callable returns, so retain
        # the marker for the lifetime of this executor worker thread.
        self._worker_context.active = True
        return method(*args, **kwargs)

    def _discard_future(self, future: Future) -> None:
        with self._lock:
            self._futures.discard(future)

    def login(self) -> Future:
        return self._submit("login", self._client.login)

    def logout(self) -> Future:
        return self._submit("logout", self._client.logout)

    def logout_local(self) -> Future:
        return self._submit("logout", self._client.logout_local)

    def restore(self, refresh_token: str) -> Future:
        return self._submit("restore", self._client.restore, refresh_token)

    def restore_saved_session(self) -> Future:
        return self._submit("restore_saved_session", self._client.restore_saved_session)

    def get_access_token(self, *, grace: int = 60, auto_login: bool = True) -> Future:
        return self._submit(
            "access_token",
            self._client.get_access_token,
            grace=grace,
            auto_login=auto_login,
        )

    def get_id_token(self, *, grace: int = 60, auto_login: bool = True) -> Future:
        return self._submit(
            "id_token",
            self._client.get_id_token,
            grace=grace,
            auto_login=auto_login,
        )

    def get_identity(self) -> Future:
        return self._submit("id_token", self._client.get_identity)

    def get_refresh_token(self) -> Future:
        return self._submit("access_token", self._client.get_refresh_token)

    def cancel_interactive_flow(self) -> None:
        self._client.cancel_interactive_flow()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            futures = tuple(self._futures)

        self._client.cancel_interactive_flow()
        for future in futures:
            future.cancel()
        if getattr(self._worker_context, "active", False):
            self._start_finalizer(futures)
            return
        self._finalize(futures)

    def _start_finalizer(self, futures) -> None:
        with self._lock:
            if self._finalizer_started:
                return
            self._finalizer_started = True
        threading.Thread(
            target=self._finalize,
            args=(futures,),
            name="coseeing-auth-finalizer",
            daemon=True,
        ).start()

    def _finalize(self, futures) -> None:
        for future in futures:
            if not future.cancelled():
                try:
                    future.result()
                except BaseException:
                    pass
        self._client.close()
        if self._owns_executor:
            self._executor.shutdown(wait=True, cancel_futures=True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
