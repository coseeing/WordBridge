import threading
from typing import Optional

import config


# Re-exported symbols and config from the package
from . import (
	OIDCManager,
	COSEEING,
	GOOGLE,
	LOGIN_REDIRECT_URI,
	LOGOUT_REDIRECT_URI,
	CALLBACK_TIMEOUT,
)

_lock = threading.RLock()
_instance: Optional[OIDCManager] = None


def get():
	"""Return a process-wide singleton instance of OIDCManager.

	Lazily constructs the manager on first call using env-configured
	parameters imported from the auth package. Thread-safe.
	"""
	global _instance
	with _lock:
		if _instance is None:
			_instance = OIDCManager(**{
				**GOOGLE,
				"login_redirect_uri": LOGIN_REDIRECT_URI,
				"logout_redirect_uri": LOGOUT_REDIRECT_URI,
				"callback_timeout": CALLBACK_TIMEOUT,
				"verify_access_token_jwt": True,
			})
			try:
				fut = _instance.restore_session_from_refresh_token_async(config.conf["WordBridge"]["settings"]["api_key"]["Coseeing"])
				fut.result()
			except Exception as e:
				print(e)
		return _instance


def shutdown():
	"""Abort any pending auth flow and drop the singleton instance."""
	global _instance
	with _lock:
		if _instance is not None:
			try:
				# Ensure any callback server or pending flow is stopped
				_instance.abort_pending_flow("shutdown")
			except Exception:
				# Best-effort cleanup; ignore errors during shutdown
				pass
			config.conf["WordBridge"]["settings"]["api_key"]["Coseeing"] = _instance.get_refresh_token()
			_instance = None


__all__ = ["get", "shutdown"]

