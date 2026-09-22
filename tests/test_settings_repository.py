import ctypes
import types

import settings_repository
from lib.catalog.document import SCHEMA_VERSION, build_catalog
from lib.catalog.model import COSEEING_GROUP
from settings_repository import LANGUAGE_FALLBACK, SettingsRepository, os_default_language


RUNNABLE = frozenset({"OpenAI"})


def catalog():
	return build_catalog(
		{
			"schema_version": SCHEMA_VERSION,
			"providers": {"OpenAI": {
				"label": "OpenAI",
				"url": "https://example.invalid",
				"setting": {},
				"timeout0": 10,
				"timeout_max": 20,
			}},
			"models": [{"provider": "OpenAI", "model": "gpt-x", "label": "GPT X"}],
			"coseeings": [{"model": "default", "label": "Coseeing default"}],
		},
		runnable_providers=RUNNABLE,
	)


def repository(**settings):
	base = {
		"corrector_config_id": "",
		"execution_channel": "",
		"language": "",
		"typo_correction_mode": "",
		"api_key": {},
		"max_char_count": 512,
		"auto_display_report": False,
		"customized_words_enable": True,
		"sound_effects_enable": True,
	}
	base.update(settings)
	return SettingsRepository(base, catalog), base


def test_an_empty_stored_selection_resolves_to_the_catalog_default():
	repo, _ = repository()

	assert repo.corrector_selection() == ("default", COSEEING_GROUP)


def test_a_stored_selection_is_honoured():
	repo, _ = repository(corrector_config_id="gpt-x&OpenAI", execution_channel="local")

	assert repo.corrector_selection() == ("gpt-x&OpenAI", "local")


def test_saving_a_selection_writes_both_keys():
	repo, settings = repository()

	repo.save_corrector_selection("gpt-x&OpenAI", "local")

	assert settings["corrector_config_id"] == "gpt-x&OpenAI"
	assert settings["execution_channel"] == "local"


def test_an_empty_language_resolves_to_the_os_default(monkeypatch):
	# Asserting against the real os_default_language() would pass even if
	# language() never consulted the probe at all, since both sides would
	# independently land on the same fallback constant on this host. Patching
	# the probe to a sentinel the constant can't equal makes this falsifiable.
	monkeypatch.setattr(settings_repository, "os_default_language", lambda: "sentinel")
	repo, _ = repository()

	assert repo.language() == "sentinel"


def test_a_stored_language_is_honoured():
	repo, _ = repository(language="zh_simplified")

	assert repo.language() == "zh_simplified"


def test_an_unknown_language_resolves_to_the_os_default(monkeypatch):
	monkeypatch.setattr(settings_repository, "os_default_language", lambda: "sentinel")
	repo, _ = repository(language="klingon")

	assert repo.language() == "sentinel"


def test_the_os_language_probe_degrades_to_the_fallback_when_windll_is_absent(monkeypatch):
	# This host's ctypes module genuinely has no windll attribute (that is
	# Windows-only), so the guarded probe's except branch must fire and
	# degrade to the exact fallback constant rather than raising -- or
	# silently returning the other language.
	monkeypatch.delattr(ctypes, "windll", raising=False)
	os_default_language.cache_clear()
	try:
		assert os_default_language() == LANGUAGE_FALLBACK
	finally:
		os_default_language.cache_clear()


def test_the_os_language_probe_resolves_a_real_windows_locale(monkeypatch):
	# Exercises the ternary at settings_repository.py that the failure-path
	# test above cannot reach: a genuine LCID lookup through
	# locale.windows_locale, for both branches of the zh_TW/zh_MO/zh_HK
	# condition. cache_clear() runs before *and* after each value so neither
	# the fake windll's result nor a prior test's cached fallback can leak.
	monkeypatch.setattr(
		ctypes,
		"windll",
		types.SimpleNamespace(kernel32=types.SimpleNamespace(GetUserDefaultUILanguage=lambda: 1028)),
		raising=False,
	)
	os_default_language.cache_clear()
	try:
		assert os_default_language() == "zh_traditional"  # 1028 -> zh_TW
	finally:
		os_default_language.cache_clear()

	monkeypatch.setattr(
		ctypes,
		"windll",
		types.SimpleNamespace(kernel32=types.SimpleNamespace(GetUserDefaultUILanguage=lambda: 2052)),
		raising=False,
	)
	os_default_language.cache_clear()
	try:
		assert os_default_language() == "zh_simplified"  # 2052 -> zh_CN
	finally:
		os_default_language.cache_clear()


def test_an_unknown_correction_mode_resolves_to_the_default():
	repo, _ = repository(typo_correction_mode="nonsense")

	assert repo.typo_correction_mode() == "standard"


def test_an_api_key_defaults_to_empty_and_is_created_on_read():
	repo, settings = repository()

	assert repo.api_key("OpenAI") == ""
	repo.save_api_key("OpenAI", "sk-test")
	assert settings["api_key"]["OpenAI"] == "sk-test"


def test_the_boolean_settings_round_trip():
	repo, settings = repository()

	repo.save_auto_display_report(True)
	repo.save_customized_words_enable(False)
	repo.save_sound_effects_enable(False)

	assert (settings["auto_display_report"], settings["customized_words_enable"], settings["sound_effects_enable"]) == (True, False, False)
	assert repo.auto_display_report() is True
	assert repo.customized_words_enable() is False
	assert repo.sound_effects_enable() is False


def test_max_char_count_round_trips():
	repo, settings = repository()

	repo.save_max_char_count(1024)

	assert settings["max_char_count"] == 1024
	assert repo.max_char_count() == 1024
