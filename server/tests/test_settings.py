from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from dotenv import dotenv_values

from app.settings import REQUIRED_VARIABLES, SettingsError, load_settings

ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"

COMPLETE = {
	"DEFAULT_CORRECTOR_CONFIG_ID": "claude-sonnet-5-5&Anthropic",
	"COSEEING_MODEL_IDS": "deepseek-flash&DeepSeek,gpt-6-luna&OpenAI",
	"SSO_ISSUER": "https://sso.example.org",
	"SSO_CLIENT_ID": "wordbridge",
	"SSO_USERINFO_URL": "https://sso.example.org/userinfo",
	"SSO_USERINFO_TIMEOUT_SECONDS": "6",
	"DB_USER": "wordbridge",
	"DB_PASS": "p@ss/word",
	"DB_HOST": "wob-db",
	"DB_PORT": "3306",
	"DATABASE": "WordBridge",
	"GUEST_TEXT_LIMIT": "128",
	"GUEST_IP_QUOTA": "0.06",
	"GUEST_GLOBAL_QUOTA": "0.3",
	"QUOTA_WINDOW_HOURS": "24",
}


def _without(name):
	return {key: value for key, value in COMPLETE.items() if key != name}


def test_a_complete_environment_loads_every_setting():
	settings = load_settings(COMPLETE)

	assert settings.default_corrector_config_id == "claude-sonnet-5-5&Anthropic"
	assert settings.coseeing_model_ids == frozenset({"deepseek-flash&DeepSeek", "gpt-6-luna&OpenAI"})
	assert settings.sso_issuer == "https://sso.example.org"
	assert settings.sso_client_id == "wordbridge"
	assert settings.sso_userinfo_url == "https://sso.example.org/userinfo"
	assert settings.sso_userinfo_timeout == 6.0
	assert settings.guest_text_limit == 128
	assert settings.guest_ip_quota == Decimal("0.06")
	assert settings.guest_global_quota == Decimal("0.3")
	assert settings.quota_window == timedelta(hours=24)


def test_every_required_variable_is_covered_here():
	assert set(REQUIRED_VARIABLES) == set(COMPLETE)


def test_the_env_example_lists_every_required_variable_and_loads():
	example = dotenv_values(ENV_EXAMPLE)

	assert set(REQUIRED_VARIABLES) <= set(example)
	settings = load_settings(example)
	assert settings.default_corrector_config_id == "claude-sonnet-5-5&Anthropic"


@pytest.mark.parametrize("name", sorted(COMPLETE))
def test_an_unset_variable_stops_startup(name):
	with pytest.raises(SettingsError, match=f"{name} is not set"):
		load_settings(_without(name))


@pytest.mark.parametrize("name", sorted(set(COMPLETE) - {"COSEEING_MODEL_IDS"}))
def test_a_blank_variable_stops_startup(name):
	with pytest.raises(SettingsError, match=f"{name} is empty"):
		load_settings(dict(COMPLETE, **{name: "  "}))


def test_an_empty_coseeing_list_means_only_the_default_is_served():
	settings = load_settings(dict(COMPLETE, COSEEING_MODEL_IDS=""))

	assert settings.coseeing_model_ids == frozenset()


def test_the_coseeing_list_is_stripped_and_skips_empty_items():
	settings = load_settings(dict(COMPLETE, COSEEING_MODEL_IDS=" gemini-3.7-flash&Google , ,"))

	assert settings.coseeing_model_ids == frozenset({"gemini-3.7-flash&Google"})


def test_every_problem_is_reported_at_once():
	environ = dict(_without("DB_PASS"), GUEST_IP_QUOTA="lots")
	del environ["SSO_ISSUER"]

	with pytest.raises(SettingsError) as raised:
		load_settings(environ)

	message = str(raised.value)
	assert "DB_PASS is not set" in message
	assert "SSO_ISSUER is not set" in message
	assert "GUEST_IP_QUOTA" in message


@pytest.mark.parametrize(
	"name, value",
	[
		("SSO_USERINFO_TIMEOUT_SECONDS", "soon"),
		("SSO_USERINFO_TIMEOUT_SECONDS", "0"),
		("SSO_USERINFO_TIMEOUT_SECONDS", "-1"),
		("SSO_USERINFO_TIMEOUT_SECONDS", "inf"),
		("DB_PORT", "mysql"),
		("DB_PORT", "0"),
		("DB_PORT", "65536"),
		("DB_PORT", "3306.5"),
		("GUEST_TEXT_LIMIT", "many"),
		("GUEST_TEXT_LIMIT", "0"),
		("GUEST_TEXT_LIMIT", "12.5"),
		("GUEST_IP_QUOTA", "lots"),
		("GUEST_IP_QUOTA", "-0.01"),
		("GUEST_IP_QUOTA", "NaN"),
		("GUEST_IP_QUOTA", "Infinity"),
		("GUEST_GLOBAL_QUOTA", "-1"),
		("QUOTA_WINDOW_HOURS", "a day"),
		("QUOTA_WINDOW_HOURS", "0"),
		("QUOTA_WINDOW_HOURS", "nan"),
	],
)
def test_a_malformed_value_stops_startup(name, value):
	with pytest.raises(SettingsError, match=name):
		load_settings(dict(COMPLETE, **{name: value}))


def test_a_zero_quota_is_allowed():
	settings = load_settings(dict(COMPLETE, GUEST_IP_QUOTA="0", GUEST_GLOBAL_QUOTA="0"))

	assert settings.guest_ip_quota == Decimal("0")
	assert settings.guest_global_quota == Decimal("0")


def test_the_database_url_escapes_the_credentials():
	settings = load_settings(COMPLETE)

	url = settings.database_url("mysql+pymysql")

	assert url.drivername == "mysql+pymysql"
	assert (url.username, url.password) == ("wordbridge", "p@ss/word")
	assert (url.host, url.port, url.database) == ("wob-db", 3306, "WordBridge")
	assert dict(url.query) == {"charset": "utf8mb4"}


def test_the_database_password_never_shows_in_the_settings_repr():
	settings = load_settings(COMPLETE)

	assert "p@ss/word" not in repr(settings)


def test_the_error_never_echoes_a_rejected_value():
	with pytest.raises(SettingsError) as raised:
		load_settings(dict(COMPLETE, DB_PORT="s3cret-looking"))

	assert "s3cret-looking" not in str(raised.value)
