from collections import defaultdict
from pathlib import Path
import csv


def load_pinyin_mapping():
	dictionary_path = Path(__file__).resolve().parent / "data" / "dict_revised_2015_20231228_csv.csv"

	string_to_pinyin = defaultdict(list)
	pinyin_to_string = defaultdict(list)
	with dictionary_path.open(encoding="utf8", newline="") as csvfile:
		reader = csv.reader(csvfile)
		for row in reader:
			pinyin_to_string[row[1]].append(row[0])
			string_to_pinyin[row[0]].append(row[1])

	return string_to_pinyin, pinyin_to_string


string_to_pinyin, pinyin_to_string = load_pinyin_mapping()
