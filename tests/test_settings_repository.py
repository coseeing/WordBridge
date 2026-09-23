import ctypes
import importlib.util
import sys
import types
from pathlib import Path

from lib.catalog.document import SCHEMA_VERSION, build_catalog
from lib.catalog.model import COSEEING_GROUP


ADDON_PATH = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge"


def _load_settings_repository():
	"""Load settings_repository.py as a package submodule, the way NVDA does.

	settings_repository.py:3 is `from .lib.catalog.selection import
	normalize_selection` -- a relative import that only resolves when the
	module is imported as part of a package. A bare top-level `import
	settings_repository` raises "attempted relative import with no known
	parent package" once that import is relative (see the fix for the
	Critical whole-branch finding). Registering a minimal package stub whose
	__path__ points at the add-on directory reproduces that shape without
	paying for a full plugin load -- the same technique
	tests/test_import_purity.py and tests/test_coseeing_auth_nvda.py's
	_load_nvda_plugin() already use for __init__.py itself.
	"""
	package_name = "wordbridge_settings_repository_probe"
	if package_name not in sys.modules:
		package = types.ModuleType(package_name)
		package.__path__ = [str(ADDON_PATH)]
		sys.modules[package_name] = package
	spec = importlib.util.spec_from_file_location(
		f"{package_name}.settings_repository",
		ADDON_PATH / "settings_repository.py",
	)
	module = importlib.util.module_from_spec(spec)
	sys.modules[spec.name] = module
	spec.loader.exec_module(module)
	return module


settings_repository = _load_settings_repository()
LANGUAGE_FALLBACK = settings_repository.LANGUAGE_FALLBACK
SettingsRepository = settings_repository.SettingsRepository
os_default_language = settings_repository.os_default_language


RUNNABLE = frozenset({"OpenAI"})


class AggregatedSectionLike:
	"""Minimal NVDA AggregatedSection interface used by SettingsRepository."""

	def __init__(self, values):
		self._values = {
			key: AggregatedSectionLike(value) if isinstance(value, dict) else value
			for key, value in values.items()
		}

	def __getitem__(self, key):
		return self._values[key]

	def __setitem__(self, key, value):
		self._values[key] = value

	def __contains__(self, key):
		return key in self._values

	def get(self, key, default=None):
		return self._values.get(key, default)


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
			"coseeings": [{"model": "default", "label": "default"}],
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


def test_api_keys_support_nvda_aggregated_sections_without_setdefault():
	settings = AggregatedSectionLike({"api_key": {}})
	repo = SettingsRepository(settings, catalog)

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


class _TooBig(Exception):
	pass


class _TooSmall(Exception):
	pass


class _RaisingSettings(dict):
	"""NVDA validates on read: an out-of-range stored value raises."""

	def __init__(self, error):
		super().__init__()
		self._error = error

	def __getitem__(self, key):
		raise self._error


def _stub_configobj_validate(monkeypatch):
	validate = types.ModuleType("configobj.validate")
	validate.VdtValueTooBigError = _TooBig
	validate.VdtValueTooSmallError = _TooSmall
	package = types.ModuleType("configobj")
	package.validate = validate
	monkeypatch.setitem(sys.modules, "configobj", package)
	monkeypatch.setitem(sys.modules, "configobj.validate", validate)


def test_max_char_count_bounds_come_from_the_injected_source():
	repo = SettingsRepository({}, catalog, max_char_count_bounds=lambda: (256, 4096))

	assert repo.max_char_count_bounds() == (256, 4096)


def test_a_too_big_max_char_count_clamps_to_the_upper_bound(monkeypatch):
	_stub_configobj_validate(monkeypatch)
	repo = SettingsRepository(_RaisingSettings(_TooBig()), catalog, max_char_count_bounds=lambda: (256, 4096))

	assert repo.max_char_count() == 4096


def test_a_too_small_max_char_count_clamps_to_the_lower_bound(monkeypatch):
	_stub_configobj_validate(monkeypatch)
	repo = SettingsRepository(_RaisingSettings(_TooSmall()), catalog, max_char_count_bounds=lambda: (256, 4096))

	assert repo.max_char_count() == 256


def test_an_unrelated_max_char_count_error_still_propagates(monkeypatch):
	_stub_configobj_validate(monkeypatch)
	repo = SettingsRepository(_RaisingSettings(KeyError("max_char_count")), catalog, max_char_count_bounds=lambda: (256, 4096))

	try:
		repo.max_char_count()
	except KeyError:
		pass
	else:
		assert False, "only range errors may be clamped"
