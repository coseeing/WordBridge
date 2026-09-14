import os

from dotenv import load_dotenv

from .OIDCManager import LoginError, LogoutError, Manager as OIDCManager

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(ENV_PATH, override=True)

LOGIN_REDIRECT_URI = os.getenv("OIDC_LOGIN_REDIRECT_URI", "http://127.0.0.1:8765/auth-callback")
LOGOUT_REDIRECT_URI = os.getenv("OIDC_LOGOUT_REDIRECT_URI", "http://127.0.0.1:8765/logout-callback")

# Callback wait timeout (seconds); default 180s
CALLBACK_TIMEOUT = int(os.getenv("OIDC_CALLBACK_TIMEOUT", "180"))

COSEEING = {
	"issuer": os.getenv("COSEEING_OIDC_AUTHORITY"),
	"client_id": os.getenv("COSEEING_OIDC_CLIENT_ID"),
	"scopes": os.getenv("COSEEING_OIDC_SCOPES"),
}

GOOGLE = {
	"issuer": os.getenv("GOOGLE_OIDC_AUTHORITY"),
	"client_id": os.getenv("GOOGLE_OIDC_CLIENT_ID"),
	"client_secret": os.getenv("GOOGLE_OIDC_CLIENT_SECRET"),
	"scopes": os.getenv("GOOGLE_OIDC_SCOPES"),
}
