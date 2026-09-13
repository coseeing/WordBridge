import struct
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from coseeing_auth import AuthConfig


def _auth_dependency_path() -> Path | None:
	if sys.platform != "win32":
		return None

	python_version = f"{sys.version_info.major}{sys.version_info.minor}"
	architecture = "win32" if struct.calcsize("P") == 4 else "win_amd64"
	return (
		Path(__file__).resolve().parents[1]
		/ "package"
		/ "_coseeing_auth_deps"
		/ f"py{python_version}-{architecture}"
	)


def _prepare_auth_dependencies() -> None:
	path = _auth_dependency_path()
	if path is not None and not path.is_dir():
		raise ImportError(f"Coseeing auth dependencies are unavailable for Python {sys.version_info[:2]}")
	if path is not None and str(path) not in sys.path:
		sys.path.insert(0, str(path))


def build_auth_config() -> "AuthConfig":
	_prepare_auth_dependencies()
	from coseeing_auth import AuthConfig

	return AuthConfig(
		issuer="https://sso.coseeing.org",
		client_id="a11yvillage",
		scopes=("openid", "profile", "email", "offline_access"),
		login_redirect_uri="http://127.0.0.1:8765/auth-callback",
		logout_redirect_uri="http://127.0.0.1:8765/logout-callback",
		callback_timeout=180,
	)
