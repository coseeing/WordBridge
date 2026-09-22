import json
from pathlib import Path

from .model import CatalogIssue


class BundledCatalogSource:
	"""Reads the shipped catalog document.

	This is the only place that knows the bundled catalog path. A future
	RemoteCatalogSource implements the same load() and returns the same
	document shape, so nothing downstream changes.
	"""

	def __init__(self, setting_dir):
		self.setting_dir = Path(setting_dir)

	def load(self) -> tuple:
		issues = []
		document = self._read_json(self.setting_dir / "catalog.json", issues)
		return document, tuple(issues)

	def _read_json(self, path, issues):
		try:
			with path.open("r", encoding="utf8") as handle:
				data = json.load(handle)
		except (OSError, ValueError) as error:
			issues.append(CatalogIssue(
				"unreadable_file",
				str(path.name),
				f"{type(error).__name__}: {error}",
			))
			return None
		if not isinstance(data, dict):
			issues.append(CatalogIssue(
				"unreadable_file",
				str(path.name),
				f"expected a JSON object, got {type(data).__name__}",
			))
			return None
		return data
