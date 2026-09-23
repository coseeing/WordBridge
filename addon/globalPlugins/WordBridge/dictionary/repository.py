import csv
from pathlib import Path


FIELDNAMES = ("text", "pronunciation")


class DictionaryRepository:
	"""The only reader and writer of the personal dictionary CSV."""

	def __init__(self, path):
		self.path = Path(path)

	def load(self) -> list[dict]:
		if not self.path.exists():
			self.path.touch()
		with self.path.open("r", encoding="utf8", newline="") as csvfile:
			return list(csv.DictReader(csvfile))

	def save(self, rows) -> None:
		with self.path.open("w", encoding="utf8", newline="") as csvfile:
			writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES)
			writer.writeheader()
			for row in rows:
				writer.writerow({name: row.get(name, "") for name in FIELDNAMES})
