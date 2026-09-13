from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from coseeing_auth import AuthConfig


def build_auth_config() -> "AuthConfig":
	from coseeing_auth import AuthConfig

	return AuthConfig(
		issuer="https://sso.coseeing.org",
		client_id="a11yvillage",
		scopes=("openid", "profile", "email", "offline_access"),
		login_redirect_uri="http://127.0.0.1:8765/auth-callback",
		logout_redirect_uri="http://127.0.0.1:8765/logout-callback",
		callback_timeout=180,
	)
