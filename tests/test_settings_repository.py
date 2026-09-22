import pytest

from lib.catalog.document import SCHEMA_VERSION, build_catalog
from lib.catalog.model import COSEEING_GROUP
from settings_repository import SettingsRepository, os_default_language


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


def test_an_empty_language_resolves_to_the_os_default():
	repo, _ = repository()

	assert repo.language() == os_default_language()


def test_a_stored_language_is_honoured():
	repo, _ = repository(language="zh_simplified")

	assert repo.language() == "zh_simplified"


def test_an_unknown_language_resolves_to_the_os_default():
	repo, _ = repository(language="klingon")

	assert repo.language() == os_default_language()


def test_the_os_language_probe_degrades_when_ctypes_is_unavailable():
	# There is no windll on this host, so the guarded probe must already be
	# taking its failure path rather than raising.
	assert os_default_language() in ("zh_traditional", "zh_simplified")


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
