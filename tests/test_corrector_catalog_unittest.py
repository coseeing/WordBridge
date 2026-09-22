import unittest
from pathlib import Path

from lib.catalog.document import build_catalog
from lib.catalog.model import COSEEING_GROUP
from lib.catalog.sources import BundledCatalogSource
from lib.llm import SUPPORTED_PROVIDERS


SETTING_DIR = Path(__file__).resolve().parents[1] / "addon" / "globalPlugins" / "WordBridge" / "setting"


def shipped_catalog():
	document, _issues = BundledCatalogSource(SETTING_DIR).load()
	return build_catalog(document, runnable_providers=SUPPORTED_PROVIDERS)


class CorrectorCatalogTests(unittest.TestCase):
	def test_google_model_labels_match_approved_text_model_catalog(self):
		self.assertEqual(
			shipped_catalog().labels_for("Google"),
			(
				"gemini-3.8-flash",
				"gemini-3.7-flash",
				"gemini-3.5-flash-lite",
				"gemini-3.1-pro",
				"gemini-3.1-flash-lite",
			),
		)

	def test_openai_and_anthropic_model_labels_match_replacement_catalog(self):
		catalog = shipped_catalog()
		self.assertEqual(catalog.labels_for("Anthropic"), ("claude-opus-5", "claude-sonnet-5"))
		self.assertEqual(
			catalog.labels_for("OpenAI"),
			("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"),
		)

	def test_default_selection_uses_first_coseeing_endpoint(self):
		self.assertEqual(
			shipped_catalog().default_selection(),
			(
				"default",
				"Coseeing",
			),
		)

	def test_provider_groups_include_coseeing_when_enabled_endpoints_exist(self):
		self.assertEqual(
			shipped_catalog().provider_groups,
			("Anthropic", "DeepSeek", "Google", "OpenAI", "Coseeing"),
		)

	def test_provider_groups_include_coseeing_last(self):
		groups = shipped_catalog().provider_groups
		self.assertEqual(groups[-1], COSEEING_GROUP)
		self.assertEqual(sorted(groups[:-1]), list(groups[:-1]))

	def test_normalize_selection_falls_back_invalid_coseeing_channel_to_local(self):
		from lib.catalog.selection import normalize_selection

		catalog = shipped_catalog()
		config_id, execution_channel = normalize_selection(
			catalog,
			"gemini-3.1-pro-preview&Google",
			"Coseeing",
		)

		self.assertEqual(config_id, "gemini-3.1-pro-preview&Google")
		self.assertEqual(execution_channel, "local")

	def test_normalize_selection_falls_back_unknown_channel_to_local(self):
		from lib.catalog.selection import normalize_selection

		catalog = shipped_catalog()
		_, execution_channel = normalize_selection(
			catalog,
			"gemini-3.1-pro-preview&Google",
			"unexpected",
		)

		self.assertEqual(execution_channel, "local")

	def test_legacy_coseeing_credentials_remain_unmodified_in_settings_data(self):
		settings = {
			"coseeing_username": "existing-user",
			"coseeing_password": "existing-password",
			"api_key": {"Coseeing": "existing-refresh"},
		}

		settings["api_key"]["OpenAI"] = "updated-key"

		self.assertEqual(settings["coseeing_username"], "existing-user")
		self.assertEqual(settings["coseeing_password"], "existing-password")
		self.assertEqual(settings["api_key"]["Coseeing"], "existing-refresh")


if __name__ == "__main__":
	unittest.main()
