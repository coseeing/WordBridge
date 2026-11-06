import unittest

from lib.catalog.model import COSEEING_GROUP
from shipped_catalog import shipped_overlay


def shipped_catalog():
	# The catalog a user sees after fetching the shipped server file.
	return shipped_overlay()


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
		self.assertEqual(
			catalog.labels_for("Anthropic"),
			("claude-opus-5.5", "claude-sonnet-5.5", "claude-haiku-5.5", "claude-opus-5", "claude-sonnet-5"),
		)
		self.assertEqual(
			catalog.labels_for("OpenAI"),
			("gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-sol", "gpt-6-luna"),
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

	def test_a_stored_coseeing_id_offered_only_locally_stays_on_coseeing(self):
		# U6 (OQ2 -> B, decided by the user 2026-11-04): the user keeps the
		# channel -- and the account and billing -- they chose. Their text
		# must not move to a local provider and their personal key.
		from lib.catalog.selection import normalize_selection

		catalog = shipped_catalog()
		for stored_id in ("gpt-6-luna&OpenAI", "deepseek-flash&DeepSeek", "gemini-3.1-pro-preview&Google"):
			with self.subTest(stored_id=stored_id):
				self.assertNotEqual(catalog.find_selection(stored_id, "local"), (-1, -1))
				self.assertEqual(
					normalize_selection(catalog, stored_id, "Coseeing"),
					("default", "Coseeing"),
				)

	def test_a_stored_coseeing_id_offered_on_coseeing_is_kept(self):
		from lib.catalog.selection import normalize_selection

		self.assertEqual(
			normalize_selection(shipped_catalog(), "default", "Coseeing"),
			("default", "Coseeing"),
		)

	def test_a_stored_local_id_still_resolves_locally(self):
		from lib.catalog.selection import normalize_selection

		self.assertEqual(
			normalize_selection(shipped_catalog(), "gpt-6-luna&OpenAI", "local"),
			("gpt-6-luna&OpenAI", "local"),
		)

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
