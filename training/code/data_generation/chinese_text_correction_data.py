#coding=utf-8

from collections import defaultdict

import chinese_converter
import csv
import jieba
import json
import random
import re
import os

from pypinyin import pinyin, Style


def get_pronounciation_info(is_traditional: bool) -> tuple:
	"""
    Get the tuple of Chinese homophone_map and homonym_map
	homophone_map: pronouciation to character
	heteronym_map: character to pronouciation

    Args:
        is_traditional (bool):	if True, the return will be info of traditional Chinese.
								Otherwisw, it will be info of simplified Chinese.

    Returns:
        pronounciation_info (tuple): (homophone_map, heteronym_map)
	"""

	char_folder = os.path.join("..", "..", "data", "Chinese Characters")
	char_file_name = "Traditional_4808.txt" if is_traditional else "Simplified_4808.txt"
	heteronym_file_name = "heteronym.csv"
	char_path = os.path.join(char_folder, char_file_name)
	heteronym_path = os.path.join(char_folder, heteronym_file_name)

	with open(char_path, 'r') as file:
		chars = [line.rstrip('\n') for line in file.readlines()]

	homophone_map = defaultdict(set)
	heteronym_map = defaultdict(set)

	for char in chars:
		pronouce = pinyin(char, style=Style.BOPOMOFO, heteronym=False)[0][0]
		homophone_map[pronouce].add(char)
		heteronym_map[char] = {pronouce}

	# Handling heteronym cases
	with open(heteronym_path, newline='') as csvfile:
		reader = csv.reader(csvfile, delimiter=',', quotechar='"')
		for row in reader:
			char = row[1] if is_traditional else chinese_converter.to_simplified(row[1])
			if row[1] not in heteronym_map:
				continue
		
			while not row[-1]:
				row.pop()
			for p in row[2:]:
				homophone_map[p].add(row[1])
				heteronym_map[row[1]].add(p)

	return homophone_map, heteronym_map

def augmentation(sentence: str, error_rate: float,
                 homophone_map: dict, heteronym_map: dict) -> str:
	"""
    Do augmentation by replacing the original characters with the homophones

    Args:
        sentence (str):	original sentence without augmentation
		error_rate (float): rate of augmentation
		homophone_map (dict): pronouciation to character
		heteronym_map (dict): character to pronouciation

    Returns:
        pronounciation_info (tuple): (homophone_map, heteronym_map)
	"""
	sentence_with_typos = ""
	for i, s in enumerate(sentence):
		if random.random() > error_rate or s not in heteronym_map:
			sentence_with_typos += s
			continue

		pronouces = list(heteronym_map[s])
		p_index = random.randint(0, len(pronouces) - 1)  # random.randint(min, max) pick integer in [min, max]
		char_candidates = list(homophone_map[pronouces[p_index]])
		c_index = random.randint(0, len(char_candidates) - 1)  # random.randint(min, max) pick integer in [min, max]
		sentence_with_typos += char_candidates[c_index]

	return sentence_with_typos

def data_generator(is_traditional: bool):
	"""
    Get the iterator of data (without augmentation)

    Args:
        is_traditional (bool):	if True, it will convert the data to traditional Chinese.
		                        We assume that the data are all in simplified Chinese.

    Returns:
        An iterator of data
	"""
	data_folder = os.path.join("..", "..", "data", "new2016zh")
	data_path = os.path.join(data_folder, "news2016zh_train.json")
	with open(data_path) as f:
		count = 0
		for line in f:
			content = json.loads(line)['content']
			if is_traditional:
				content = chinese_converter.to_traditional(content)

			sentence_segment = ""
			for segment in jieba.cut(content):
				sentence_segment += segment
				if random.random() < 0.1:
					yield sentence_segment
					sentence_segment = ""
			if sentence_segment:
				yield sentence_segment


if __name__ == "__main__":
	"""
	The output file will be a *.jsonl file contains encoded strings.
	Please run "openai tools fine_tunes.prepare_data -f <LOCAL_FILE>"
	to reformat the file.
	"""

	random.seed(0)
	error_rate = 0.2
	is_traditional=True
	sample_count = 200

	homophone_map, heteronym_map = get_pronounciation_info(is_traditional=is_traditional)	
	output_folder = os.path.join("..", "..", "data", "typos_completion")
	output_name = f"data_{sample_count}.jsonl"
	output_path = os.path.join(output_folder, output_name)
	
	with open(output_path, 'w') as f:
		for i, data in enumerate(data_generator(is_traditional=is_traditional)):
			if i == sample_count:
				break
			
			data_aug = augmentation(data, error_rate, homophone_map, heteronym_map)
			print(f"{{\"prompt\": \"{data_aug}\", \"completion\": \"{data}\"}}")
			json_str = json.dumps({"prompt": data_aug, "completion": data})  # Encoding string
			f.write(json_str + '\n')
