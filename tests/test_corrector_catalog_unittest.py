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
	def test_config_manager_projects_coseeing_items_under_local_and_coseeing_groups(self):
		from configManager import ConfigManager, make_corrector_config_id

		manager = ConfigManager(CORRECTOR_DIR)
		config_id = make_corrector_config_id("gpt-5.4-mini-2026-03-17", "OpenAIResponse")

		local_items = [
			item for item in manager.endpoints["OpenAIResponse"]
			if item.corrector_config_id == config_id
		]
		coseeing_items = [
			item for item in manager.endpoints["Coseeing"]
			if item.corrector_config_id == config_id
		]

		self.assertEqual(len(local_items), 1)
		self.assertEqual(local_items[0].execution_channel, "local")
		self.assertEqual(len(coseeing_items), 1)
		self.assertEqual(coseeing_items[0].execution_channel, "Coseeing")

	def test_coseeing_projection_preserves_backend_catalog_order(self):
		from configManager import ConfigManager

		manager = ConfigManager(CORRECTOR_DIR)

		projected_models = [item.config.model for item in manager.endpoints["Coseeing"]]
		self.assertEqual(
			projected_models,
			[
				"gpt-5.4-mini-2026-03-17",
				"gpt-5.4-nano-2026-03-17",
				"gpt-5.1-2025-11-13",
				"gpt-4.1-2025-04-14",
				"gpt-4.1-mini-2025-04-14",
				"gpt-4.1-nano-2025-04-14",
			],
		)

	def test_default_selection_uses_first_coseeing_item(self):
		from configManager import ConfigManager

		manager = ConfigManager(CORRECTOR_DIR)

		self.assertEqual(
			manager.default_selection(),
			(
				"gpt-5.4-mini-2026-03-17&OpenAIResponse",
				"Coseeing",
			),
		)

	def test_provider_groups_put_coseeing_first_and_keep_others_alphabetical(self):
		from configManager import ConfigManager

		manager = ConfigManager(CORRECTOR_DIR)

		self.assertEqual(
			manager.provider_groups,
			[
				"Coseeing",
				"Anthropic",
				"DeepSeek",
				"Google",
				"OpenAIChatCompletion",
				"OpenAIResponse",
			],
		)

	def test_normalize_selection_preserves_valid_coseeing_channel(self):
		from configManager import ConfigManager, normalize_selection

		manager = ConfigManager(CORRECTOR_DIR)
		config_id, execution_channel, config = normalize_selection(
			manager,
			"gpt-5.4-mini-2026-03-17&OpenAIResponse",
			"Coseeing",
		)

		self.assertEqual(config_id, "gpt-5.4-mini-2026-03-17&OpenAIResponse")
		self.assertEqual(execution_channel, "Coseeing")
		self.assertTrue(config.coseeing)

	def test_normalize_selection_falls_back_invalid_coseeing_channel_to_local(self):
		from configManager import ConfigManager, normalize_selection

		manager = ConfigManager(CORRECTOR_DIR)
		config_id, execution_channel, config = normalize_selection(
			manager,
			"gpt-5.4-2026-03-05&OpenAIResponse",
			"Coseeing",
		)

		self.assertEqual(config_id, "gpt-5.4-2026-03-05&OpenAIResponse")
		self.assertEqual(execution_channel, "local")
		self.assertFalse(config.coseeing)

	def test_normalize_selection_falls_back_unknown_channel_to_local(self):
		from configManager import ConfigManager, normalize_selection

		manager = ConfigManager(CORRECTOR_DIR)
		_, execution_channel, _ = normalize_selection(
			manager,
			"gpt-5.4-mini-2026-03-17&OpenAIResponse",
			"unexpected",
		)

		self.assertEqual(execution_channel, "local")


if __name__ == "__main__":
	unittest.main()
