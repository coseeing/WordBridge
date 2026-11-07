"""Deployment settings, read once from the environment.

Every value a deployment chooses comes from an environment variable, and
none has a built-in fallback: a server must never run on a value nobody
chose for it. load_settings() checks every variable and raises one
SettingsError naming every missing or malformed one, so a deployment with
a gap stops at startup with the whole list instead of one name per restart.

server/.env is loaded into the environment when this module is imported.
It never overrides a variable that is already set. server/.env.example
lists every variable with a note on what it does.

Limits tied to a database column or to the correction algorithm (the IP
and user name lengths, the 8000 character request limit) stay in the code:
they are not a deployment's choice.
"""

import math
import os
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

REQUIRED_VARIABLES = (
	"DEFAULT_CORRECTOR_CONFIG_ID",
	"COSEEING_MODEL_IDS",
	"SSO_ISSUER",
	"SSO_CLIENT_ID",
	"SSO_USERINFO_URL",
	"SSO_USERINFO_TIMEOUT_SECONDS",
	"DB_USER",
	"DB_PASS",
	"DB_HOST",
	"DB_PORT",
	"DATABASE",
	"GUEST_TEXT_LIMIT",
	"GUEST_IP_QUOTA",
	"GUEST_GLOBAL_QUOTA",
	"QUOTA_WINDOW_HOURS",
	"CLIENT_IP_SOURCE",
)

# Where the client address comes from (app/client_ip.py): "cloudflare" when
# Cloudflare proxies the domain, "proxy" when Cloudflare only serves DNS.
CLIENT_IP_SOURCES = ("cloudflare", "proxy")

# Variables where an empty value is a choice rather than a gap.
_MAY_BE_EMPTY = frozenset({"COSEEING_MODEL_IDS"})


class SettingsError(ValueError):
	"""One or more deployment settings are missing or malformed."""


@dataclass(frozen=True)
class Settings:
	default_corrector_config_id: str
	# The non-default corrector config ids Coseeing serves. Released add-ons
	# offered these on their Coseeing channel and keep sending them; the
	# catalog the server publishes at GET / has no Coseeing channel, so the
	# list is the server's own. Empty means only "default" is served.
	coseeing_model_ids: frozenset
	sso_issuer: str
	sso_client_id: str
	sso_userinfo_url: str
	sso_userinfo_timeout: float
	db_user: str
	db_pass: str = field(repr=False)
	db_host: str
	db_port: int
	database: str
	guest_text_limit: int
	guest_ip_quota: Decimal
	guest_global_quota: Decimal
	quota_window: timedelta
	client_ip_source: str

	def database_url(self, drivername: str) -> URL:
		return URL.create(
			drivername,
			username=self.db_user,
			password=self.db_pass,
			host=self.db_host,
			port=self.db_port,
			database=self.database,
			query={"charset": "utf8mb4"},
		)


def load_settings(environ=None) -> Settings:
	"""Build the settings from `environ` (os.environ by default).

	Raises SettingsError listing every problem. The message names the
	variables but never repeats a value, so a password pasted into the
	wrong variable does not end up in a log.
	"""
	reader = _Reader(os.environ if environ is None else environ)
	values = {
		"default_corrector_config_id": reader.text("DEFAULT_CORRECTOR_CONFIG_ID"),
		"coseeing_model_ids": reader.id_list("COSEEING_MODEL_IDS"),
		"sso_issuer": reader.text("SSO_ISSUER"),
		"sso_client_id": reader.text("SSO_CLIENT_ID"),
		"sso_userinfo_url": reader.text("SSO_USERINFO_URL"),
		"sso_userinfo_timeout": reader.positive_number("SSO_USERINFO_TIMEOUT_SECONDS"),
		"db_user": reader.text("DB_USER"),
		"db_pass": reader.raw("DB_PASS"),
		"db_host": reader.text("DB_HOST"),
		"db_port": reader.port("DB_PORT"),
		"database": reader.text("DATABASE"),
		"guest_text_limit": reader.positive_integer("GUEST_TEXT_LIMIT"),
		"guest_ip_quota": reader.amount("GUEST_IP_QUOTA"),
		"guest_global_quota": reader.amount("GUEST_GLOBAL_QUOTA"),
		"quota_window": reader.hours("QUOTA_WINDOW_HOURS"),
		"client_ip_source": reader.choice("CLIENT_IP_SOURCE", CLIENT_IP_SOURCES),
	}
	if reader.problems:
		raise SettingsError("Deployment settings are incomplete: " + "; ".join(reader.problems))
	return Settings(**values)


class _Reader:
	def __init__(self, environ):
		self._environ = environ
		self.problems = []

	def raw(self, name):
		"""The value as set, or None after recording why it is unusable."""
		value = self._environ.get(name)
		if value is None:
			self.problems.append(f"{name} is not set")
			return None
		if not value.strip() and name not in _MAY_BE_EMPTY:
			self.problems.append(f"{name} is empty")
			return None
		return value

	def text(self, name):
		value = self.raw(name)
		return None if value is None else value.strip()

	def choice(self, name, options):
		value = self.text(name)
		if value is None:
			return None
		if value not in options:
			return self._reject(name, "must be " + " or ".join(options))
		return value

	def id_list(self, name):
		value = self.raw(name)
		if value is None:
			return None
		return frozenset(item.strip() for item in value.split(",") if item.strip())

	def positive_number(self, name):
		number = self._parse(name, float, "a number")
		if number is None:
			return None
		if not math.isfinite(number) or number <= 0:
			return self._reject(name, "must be a number greater than 0")
		return number

	def positive_integer(self, name):
		number = self._parse(name, int, "a whole number")
		if number is None:
			return None
		if number <= 0:
			return self._reject(name, "must be a whole number greater than 0")
		return number

	def port(self, name):
		number = self._parse(name, int, "a whole number")
		if number is None:
			return None
		if not 1 <= number <= 65535:
			return self._reject(name, "must be a port number from 1 to 65535")
		return number

	def amount(self, name):
		amount = self._parse(name, Decimal, "a number")
		if amount is None:
			return None
		if not amount.is_finite() or amount < 0:
			return self._reject(name, "must be a number of 0 or more")
		return amount

	def hours(self, name):
		number = self.positive_number(name)
		return None if number is None else timedelta(hours=number)

	def _parse(self, name, kind, description):
		value = self.text(name)
		if value is None:
			return None
		try:
			return kind(value)
		except (ValueError, InvalidOperation):
			return self._reject(name, f"must be {description}")

	def _reject(self, name, reason):
		self.problems.append(f"{name} {reason}")


load_dotenv(ENV_FILE)
SETTINGS = load_settings()
