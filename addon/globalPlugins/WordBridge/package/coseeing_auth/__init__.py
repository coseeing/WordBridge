from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from .client import CoseeingAuthClient
	from .errors import (
		AuthError,
		AuthFlowInProgressError,
		ConfigurationError,
		DiscoveryError,
		LoginError,
		LogoutError,
		RestoreError,
		TokenUnavailableError,
		TokenValidationError,
	)
	from .future import FutureAuthClient
	from .models import AuthConfig, AuthResult, Identity, LogoutMode, LogoutResult

__all__ = [
    "AuthConfig",
    "AuthError",
    "AuthFlowInProgressError",
    "AuthResult",
    "CoseeingAuthClient",
    "FutureAuthClient",
    "ConfigurationError",
    "DiscoveryError",
    "Identity",
    "LoginError",
    "LogoutError",
    "LogoutMode",
    "LogoutResult",
    "RestoreError",
    "TokenUnavailableError",
    "TokenValidationError",
]


def __getattr__(name: str):
	if name in {"AuthConfig", "AuthResult", "Identity", "LogoutMode", "LogoutResult"}:
		from . import models

		return getattr(models, name)
	if name == "FutureAuthClient":
		from .future import FutureAuthClient

		return FutureAuthClient
	if name in {
		"AuthError",
		"AuthFlowInProgressError",
		"ConfigurationError",
		"DiscoveryError",
		"LoginError",
		"LogoutError",
		"RestoreError",
		"TokenUnavailableError",
		"TokenValidationError",
	}:
		from . import errors

		return getattr(errors, name)
	if name == "CoseeingAuthClient":
		from .client import CoseeingAuthClient

		return CoseeingAuthClient
	raise AttributeError(name)
