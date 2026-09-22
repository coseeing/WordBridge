import json
from pathlib import Path

from .document import SCHEMA_VERSION
from .model import CatalogIssue


# Display names, lifted from configManager.LABEL_DICT. Not translated: every
# entry maps a name to itself apart from gemini-3.1-pro-preview, which is a
# rename. lib/catalog cannot reach NVDA's translation builtin, and a model
# name is not translatable content.
BUNDLED_LABELS = {
	"Anthropic": "Anthropic",
	"Coseeing": "Coseeing",
	"DeepSeek": "DeepSeek",
	"Google": "Google",
	"OpenAI": "OpenAI",
	"claude-opus-5": "claude-opus-5",
	"claude-sonnet-5": "claude-sonnet-5",
	"deepseek-v4-flash": "deepseek-v4-flash",
	"deepseek-v4-pro": "deepseek-v4-pro",
	"gemini-3.1-pro-preview": "gemini-3.1-pro",
	"gemini-3.1-flash-lite": "gemini-3.1-flash-lite",
	"gemini-3.5-flash-lite": "gemini-3.5-flash-lite",
	"gemini-3.7-flash": "gemini-3.7-flash",
	"gemini-3.8-flash": "gemini-3.8-flash",
	"gpt-5.6-sol": "gpt-5.6-sol",
	"gpt-5.6-terra": "gpt-5.6-terra",
	"gpt-5.6-luna": "gpt-5.6-luna",
}


class BundledCatalogSource:
	"""Flattens the shipped setting/ tree into one catalog document.

	This is the only place that knows the on-disk layout. A future
	RemoteCatalogSource implements the same load() and returns the same
	document shape, so nothing downstream changes.
	"""

	def __init__(self, setting_dir):
		self.setting_dir = Path(setting_dir)

	def load(self) -> tuple:
		issues = []
		price = self._read_json(self.setting_dir / "price.json", issues) or {}
		providers = {}
		for path in sorted((self.setting_dir / "provider").glob("*.json")):
			data = self._read_json(path, issues)
			if data is None:
				continue
			providers[path.stem] = {
				"label": BUNDLED_LABELS.get(path.stem, path.stem),
				"url": data.get("url"),
				"setting": data.get("setting"),
				"timeout0": data.get("timeout0"),
				"timeout_max": data.get("timeout_max"),
			}

		models = []
		coseeings = []
		for path in sorted((self.setting_dir / "ai").glob("*.json")):
			data = self._read_json(path, issues)
			if data is None:
				continue
			model = data.get("model")
			provider = data.get("provider")
			active = data.get("active", True)
			label = BUNDLED_LABELS.get(model, model)
			if provider is None:
				# No provider means no local offer: the server serves it alone.
				coseeings.append({"model": model, "label": label, "active": active})
				continue
			key = f"{model}&{provider}"
			entry = {
				"provider": provider,
				"model": model,
				"label": label,
				"active": active,
			}
			priced = price.get(key)
			if priced:
				entry["pricing"] = priced.get("pricing")
				entry["usage_key"] = priced.get("usage_key")
			models.append(entry)
			if data.get("coseeing"):
				coseeings.append({
					"model": model,
					"provider": provider,
					"label": label,
					"active": active,
				})

		document = {
			"schema_version": SCHEMA_VERSION,
			"providers": providers,
			"models": models,
			"coseeings": coseeings,
		}
		return document, tuple(issues)

	def _read_json(self, path, issues):
		try:
			with path.open("r", encoding="utf8") as handle:
				return json.load(handle)
		except (OSError, ValueError) as error:
			issues.append(CatalogIssue(
				"unreadable_file",
				str(path.name),
				f"{type(error).__name__}: {error}",
			))
			return None
