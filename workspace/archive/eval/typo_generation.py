import os
import random
import string
import sys

from chinese_converter import to_simplified, to_traditional

path = os.path.dirname(__file__)
api_path = os.path.join(path, "..", "..", "..", "addon", "globalPlugins", "WordBridge")
sys.path.insert(0, api_path)

from lib.tasks.typo.chinese_dictionary import get_pinyin_to_string, get_string_to_pinyin


def typo_augmentation(text: str, is_traditional: bool, error_rate: float = 0.125) -> str:
	if not is_traditional:
		text = to_traditional(text)

	string_to_pinyin = get_string_to_pinyin()
	pinyin_to_string = get_pinyin_to_string()
	text_aug = ""
	for char in text:
		if char not in string_to_pinyin or random.random() > error_rate:
			text_aug += char
			continue

		pronounce = random.choice(string_to_pinyin[char])
		char_aug = random.choice(pinyin_to_string[pronounce])
		text_aug += char_aug

	if not is_traditional:
		text_aug = to_simplified(text_aug)

	return text_aug


if __name__ == "__main__":

	random.seed(0)
	error_rate = 0.1
	is_traditional = True
	file_name = "gpt4_250_sentence_gt.txt"

	random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=20))
	output_name = f"gpt4_250_sentence_aug_err_{error_rate}_{random_str}.txt"
	file_folder = os.path.join(".", "data")
	file_path = os.path.join(file_folder, file_name)
	output_path = os.path.join(file_folder, output_name)

	sentences_aug = []
	with open(file_path, 'r') as f:
		lines = f.readlines()
		for sentence in lines:
			sentence = sentence.replace('\n', '')
			sentence = typo_augmentation(sentence, is_traditional, error_rate=error_rate)
			sentences_aug.append(sentence)
			print(sentence)

	with open(output_path, 'w') as f:
		for sentence in sentences_aug:
			f.write(sentence + '\n')
