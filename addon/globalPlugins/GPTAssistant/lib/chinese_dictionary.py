from collections import defaultdict

import csv
import os


def load_dictionary():

	char_to_pronouce = defaultdict(set)

	with open(dict_path, newline='') as csvfile:
		reader = csv.reader(csvfile)
		next(reader)
		for row in reader:
			char_to_pronouce[row[0]].add(row[2])
			char_to_pronouce[row[1]].add(row[2])

			if len(row) == 6:
				for char in row[5].split('，'):
					char_to_pronouce[char].add(row[2])

	return char_to_pronouce


folder_absolute_path = os.path.dirname(os.path.abspath(__file__))
dict_path = os.path.join(folder_absolute_path, "..", "data", "chinese_dictionary.csv")
char_to_pronouce = load_dictionary()
