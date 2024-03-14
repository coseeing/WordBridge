from collections import defaultdict

import csv
import os


def load_dictionary(dictionary_path: str):

	char_to_pronounce = defaultdict(set)
	pronounce_to_char_traditional = defaultdict(set)
	pronounce_to_char_simplified = defaultdict(set)

	with open(dictionary_path, encoding="utf8", newline="") as csvfile:
		reader = csv.reader(csvfile)
		next(reader)
		for row in reader:
			row[2] = row[2].replace('5', '')
			char_to_pronounce[row[0]].update(set(row[2].split('/')))
			char_to_pronounce[row[1]].update(set(row[2].split('/')))
			for phone in row[2].split('/'):
				pronounce_to_char_traditional[phone].add(row[0])
				pronounce_to_char_simplified[phone].add(row[1])

			"""
			Skip this part since we are not sure whether row[5] are traditional or simplified
			if len(row) == 6:
				for char in row[5].split("，"):
					char_to_pronounce[char].add(row[2])
			"""

	return char_to_pronounce, pronounce_to_char_traditional, pronounce_to_char_simplified


folder_absolute_path = os.path.dirname(os.path.abspath(__file__))
dict_path = os.path.join(folder_absolute_path, "..", "data", "chinese_dictionary_pinyin_number.csv")
char_to_pronounce, pronounce_to_char_traditional, pronounce_to_char_simplified = load_dictionary(dict_path)
