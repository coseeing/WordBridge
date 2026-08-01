import sys
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge"
PACKAGE_PATH = ADDON_PATH / "package"
CORRECTOR_DIR = ADDON_PATH / "setting" / "corrector"

sys.path.insert(0, str(ADDON_PATH))
sys.path.insert(0, str(PACKAGE_PATH))

addon_handler = types.ModuleType("addonHandler")
addon_handler.initTranslation = lambda: None
sys.modules.setdefault("addonHandler", addon_handler)


class CorrectorCatalogTests(unittest.TestCase):
	def test_openai_and_anthropic_model_labels_match_replacement_catalog(self):
		from configManager import ConfigManager

		manager = ConfigManager(CORRECTOR_DIR)
		manager.provider = "Anthropic"
		self.assertEqual(manager.model_labels, ["claude-opus-5", "claude-sonnet-5"])
		manager.provider = "OpenAI"
		self.assertEqual(
			manager.model_labels,
			["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"],
		)

	def test_default_selection_uses_first_anthropic_model_locally(self):
		from configManager import ConfigManager

		manager = ConfigManager(CORRECTOR_DIR)

		self.assertEqual(
			manager.default_selection(),
			(
				"claude-opus-5&Anthropic",
				"local",
			),
		)

	def test_provider_groups_preserve_unaffected_providers_without_coseeing(self):
		from configManager import ConfigManager

		manager = ConfigManager(CORRECTOR_DIR)

		self.assertEqual(
			manager.provider_groups,
			["Anthropic", "DeepSeek", "Google", "OpenAI"],
		)

	def test_normalize_selection_falls_back_invalid_coseeing_channel_to_local(self):
		from configManager import ConfigManager, normalize_selection

		manager = ConfigManager(CORRECTOR_DIR)
		config_id, execution_channel, config = normalize_selection(
			manager,
			"gemini-3.1-pro-preview&Google",
			"Coseeing",
		)

		self.assertEqual(config_id, "gemini-3.1-pro-preview&Google")
		self.assertEqual(execution_channel, "local")
		self.assertFalse(config.coseeing)

	def test_normalize_selection_falls_back_unknown_channel_to_local(self):
		from configManager import ConfigManager, normalize_selection

		manager = ConfigManager(CORRECTOR_DIR)
		_, execution_channel, _ = normalize_selection(
			manager,
			"gemini-3.1-pro-preview&Google",
			"unexpected",
		)

		self.assertEqual(execution_channel, "local")


if __name__ == "__main__":
	unittest.main()
