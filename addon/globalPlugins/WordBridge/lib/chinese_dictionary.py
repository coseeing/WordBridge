from collections import defaultdict

import csv
import os


def load_pinyin_mapping():
	file_dir_path = os.path.dirname(os.path.abspath(__file__))
	dictionary_path = os.path.join(file_dir_path, "..", "data", "dict_revised_2015_20231228_csv.csv")

	string_to_pinyin = defaultdict(list)
	pinyin_to_string = defaultdict(list)
	with open(dictionary_path, encoding="utf8", newline="") as csvfile:
		reader = csv.reader(csvfile)
		for row in reader:
			pinyin_to_string[row[1]].append(row[0])
			string_to_pinyin[row[0]].append(row[1])

	return string_to_pinyin, pinyin_to_string

string_to_pinyin, pinyin_to_string = load_pinyin_mapping()