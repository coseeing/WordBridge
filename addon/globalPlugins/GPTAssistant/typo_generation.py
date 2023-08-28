import os
import random
import string

from lib.utils import typo_augmentation


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
