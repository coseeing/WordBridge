from collections import defaultdict

import csv
import os


def load_dictionary(dictionary_path: str):

	char_to_pronounce = defaultdict(set)

	with open(dictionary_path, encoding="utf8", newline='') as csvfile:
		reader = csv.reader(csvfile)
		next(reader)
		for row in reader:
			char_to_pronounce[row[0]].add(row[2])
			char_to_pronounce[row[1]].add(row[2])

			if len(row) == 6:
				for char in row[5].split('，'):
					char_to_pronounce[char].add(row[2])

	return char_to_pronounce


folder_absolute_path = os.path.dirname(os.path.abspath(__file__))
dict_path = os.path.join(folder_absolute_path, "..", "data", "chinese_dictionary.csv")
char_to_pronounce = load_dictionary(dict_path)
