from collections import defaultdict
from pathlib import Path
import csv
import threading


DICTIONARY_PATH = Path(__file__).resolve().parent / "data" / "dict_revised_2015_20231228_csv.csv"

# Parsing this file costs about 3.6MB of I/O, and this module sits on NVDA's
# start-up import path through lib/tasks/typo/utils.py. The lock (rather than
# lru_cache) is what stops several parallel_map workers each parsing it on a
# cold first access, and what stops any caller observing a half-built mapping.
_MAPPINGS = None
_MAPPINGS_LOCK = threading.Lock()


def load_pinyin_mapping():
	string_to_pinyin = defaultdict(list)
	pinyin_to_string = defaultdict(list)
	with DICTIONARY_PATH.open(encoding="utf8", newline="") as csvfile:
		reader = csv.reader(csvfile)
		for row in reader:
			pinyin_to_string[row[1]].append(row[0])
			string_to_pinyin[row[0]].append(row[1])

	return string_to_pinyin, pinyin_to_string


def _get_mappings():
	global _MAPPINGS
	if _MAPPINGS is None:
		with _MAPPINGS_LOCK:
			if _MAPPINGS is None:
				# A missing or unreadable dictionary propagates. Degrading to
				# an empty mapping would make every character look like it has
				# no pronunciation, which reads as a correctness bug far away
				# from here.
				_MAPPINGS = load_pinyin_mapping()
	return _MAPPINGS


def get_string_to_pinyin():
	return _get_mappings()[0]


def get_pinyin_to_string():
	return _get_mappings()[1]
