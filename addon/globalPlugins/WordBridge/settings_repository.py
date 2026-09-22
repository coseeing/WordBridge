from functools import lru_cache

from .lib.catalog.selection import normalize_selection


LANGUAGE_VALUES = ["zh_traditional", "zh_simplified"]
LANGUAGE_FALLBACK = "zh_traditional"
TYPO_CORRECTION_MODE_VALUES = ["standard", "lite"]
TYPO_CORRECTION_MODE_DEFAULT = "standard"


@lru_cache(maxsize=1)
def os_default_language() -> str:
	"""The UI language NVDA's host is running in, resolved lazily.

	This used to run at dialogs.py import time. Off Windows -- and on any
	runtime where the call fails -- it degrades to Traditional Chinese rather
	than taking the module's import down with it.
	"""
	try:
		import ctypes
		import locale

		code = locale.windows_locale[ctypes.windll.kernel32.GetUserDefaultUILanguage()]
	except Exception:
		return LANGUAGE_FALLBACK
	return LANGUAGE_FALLBACK if code in ("zh_TW", "zh_MO", "zh_HK") else "zh_simplified"


class SettingsRepository:
	"""The only place that touches config.conf["WordBridge"]["settings"].

	It also owns the two resolutions that let the config spec defaults be
	static strings: an empty corrector selection becomes the catalog's
	default, and an empty language becomes the OS UI language.
	"""

	def __init__(self, settings, current_catalog):
		self._settings = settings
		self._catalog = current_catalog

	def corrector_selection(self) -> tuple:
		return normalize_selection(
			self._catalog(),
			self._settings.get("corrector_config_id", ""),
			self._settings.get("execution_channel", ""),
		)

	def save_corrector_selection(self, corrector_config_id: str, execution_channel: str) -> None:
		self._settings["corrector_config_id"] = corrector_config_id
		self._settings["execution_channel"] = execution_channel

	def language(self) -> str:
		value = self._settings.get("language", "")
		return value if value in LANGUAGE_VALUES else os_default_language()

	def save_language(self, value: str) -> None:
		self._settings["language"] = value

	def typo_correction_mode(self) -> str:
		value = self._settings.get("typo_correction_mode", "")
		return value if value in TYPO_CORRECTION_MODE_VALUES else TYPO_CORRECTION_MODE_DEFAULT

	def save_typo_correction_mode(self, value: str) -> None:
		self._settings["typo_correction_mode"] = value

	def api_key(self, provider: str) -> str:
		keys = self._settings["api_key"]
		if provider not in keys:
			keys[provider] = ""
		return keys[provider]

	def save_api_key(self, provider: str, value: str) -> None:
		self._settings["api_key"][provider] = value

	def max_char_count(self) -> int:
		return self._settings["max_char_count"]

	def save_max_char_count(self, value: int) -> None:
		self._settings["max_char_count"] = value

	def auto_display_report(self) -> bool:
		return self._settings["auto_display_report"]

	def save_auto_display_report(self, value: bool) -> None:
		self._settings["auto_display_report"] = value

	def customized_words_enable(self) -> bool:
		return self._settings["customized_words_enable"]

	def save_customized_words_enable(self, value: bool) -> None:
		self._settings["customized_words_enable"] = value

	def sound_effects_enable(self) -> bool:
		return self._settings["sound_effects_enable"]

	def save_sound_effects_enable(self, value: bool) -> None:
		self._settings["sound_effects_enable"] = value
