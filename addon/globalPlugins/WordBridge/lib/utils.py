import random
import string

from difflib import SequenceMatcher
from typing import Dict, List
# from chinese_converter import to_simplified, to_traditional
from .chinese_dictionary import char_to_pronounce
from .chinese_dictionary import pronounce_to_char_traditional, pronounce_to_char_simplified
from hanzidentifier import has_chinese, identify
from hanzidentifier import MIXED, SIMPLIFIED, TRADITIONAL
from pypinyin import pinyin, Style

try:
	from languageHandler import getLanguage
	from speech.speech import getCharDescListFromText
except ImportError:
	getLanguage = None
	getCharDescListFromText = None

# Characters used for text segmentation
SEPERATOR = "﹐，,.。﹒．｡:։׃∶˸︓﹕：!ǃⵑ︕！;;︔﹔；?︖﹖？⋯ \n\r\t" + string.punctuation


def get_phone(char: str) -> List:
	phones = char_to_pronounce[char] | set(pinyin(char, style=Style.TONE3, heteronym=True)[0])
	return list(phones)


def typo_augmentation(text: str, is_traditional: bool, error_rate: float = 0.125) -> str:
	text_aug = ""
	p2c_dict = pronounce_to_char_traditional if is_traditional else pronounce_to_char_simplified

	for char in text:
		if char not in char_to_pronounce or random.random() > error_rate:
			text_aug += char
			continue

		pronounce = random.choice(list(char_to_pronounce[char]))
		char_aug = random.choice(list(p2c_dict[pronounce]))
		text_aug += char_aug

	return text_aug


def text_segmentation(text: str, max_length: int = 50) -> tuple:
	"""
	This function can be used to split a string into substrings based on a set of specified separators or
	a maximum length limit.

	Parameters:
		text (str): A string that needs to be partitioned into substrings based on certain separators or
					a maximum length limit.
		max_length (int): The maximum length of each substring. If a substring reaches this length, it will be
							partitioned at the next separator encountered.
	Returns:
		A list of substrings that are separated by certain separators or a maximum length limit.
	"""

	partitions = []
	separators = []

	word = ""
	for char in text:
		if char in SEPERATOR or (not has_chinese(char)):
			separators.append(char)
			partitions.append(word)
			word = ""
			continue

		if len(word) >= max_length:
			separators.append("")
			partitions.append(word)
			word = ""

		word += char

	if word:
		partitions.append(word)
		separators.append("")

	return partitions, separators


def analyze_diff(char_original: str, char_corrected: str) -> List:
	"""
	This function takes in two single-character strings, `char_original` and `char_corrected`, and returns a list
	of tags that describe the differences between the two characters.

	Parameters:
		char_original (str): A single-character string representing the original character.
		char_corrected (str): A single-character string representing the corrected character.

	Returns:
		A list of tags that describe the differences between the two input characters.
	"""
	assert len(char_original) == len(char_corrected) == 1, "Length of char_original, char_corrected should be 1."
	tags = []

	# char_simplified = to_simplified(char_original)
	# char_traditional = to_traditional(char_original)
	char_simplified = char_original
	char_traditional = char_original
	if char_original != char_simplified and char_simplified == char_corrected:
		tags.append("Tranditional to simplified")
	elif char_original != char_traditional and char_traditional == char_corrected:
		tags.append("Simplified to tranditional")

	if char_to_pronounce[char_original] | char_to_pronounce[char_corrected]:
		tags.append("Share the same pronunciation")
	else:
		tags.append("Do not share the same pronunciation")

	return tags


def has_simplified_chinese_char(string: str):
	return identify(string) in [SIMPLIFIED, MIXED]


def has_traditional_chinese_char(string: str):
	return identify(string) in [TRADITIONAL, MIXED]


def get_descs(string: str) -> str:
	if not string or getLanguage is None or getCharDescListFromText is None:
		return ""

	return getCharDescListFromText(string, getLanguage())


def strings_diff(string_before: str, string_after: str) -> Dict:

	# operation (op) is replace or insert or delete

	matcher = SequenceMatcher(None, string_before, string_after)
	diff = []
	for op, index_start_before, index_end_before, index_start_after, index_end_after in matcher.get_opcodes():
		if op == "equal":
			operation_dict = {
				"operation": op,
				"before_text": string_before[index_start_before:index_end_before],
				"after_text": string_after[index_start_after:index_end_after],
				"index_start_before": index_start_before,
				"index_end_before": index_end_before,
				"index_start_after": index_start_after,
				"index_end_after": index_end_after,
				"before_descs": "",
				"after_descs": "",
				"tags": None,
			}
			diff.append(operation_dict)
			continue
		elif op != "replace":
			operation_dict = {
				"operation": op,
				"before_text": string_before[index_start_before:index_end_before],
				"after_text": string_after[index_start_after:index_end_after],
				"index_start_before": index_start_before,
				"index_end_before": index_end_before,
				"index_start_after": index_start_after,
				"index_end_after": index_end_after,
				"before_descs": get_descs(string_before[index_start_before:index_end_before]),
				"after_descs": get_descs(string_after[index_start_after:index_end_after]),
				"tags": None,
			}
			diff.append(operation_dict)
			continue

		for i in range(index_end_before - index_start_before):
			operation_dict = {
				"operation": op,
				"before_text": string_before[(index_start_before + i):(index_start_before + i + 1)],
				"after_text": string_after[(index_start_after + i):(index_start_after + i + 1)],
				"index_start_before": index_start_before + i,
				"index_end_before": index_start_before + i + 1,
				"index_start_after": index_start_after + i,
				"index_end_after": index_start_after + i + 1,
				"before_descs": get_descs(string_before[(index_start_before + i):(index_start_before + i + 1)]),
				"after_descs": get_descs(string_after[(index_start_after + i):(index_start_after + i + 1)]),
				"tags": None,
			}
			operation_dict["tags"] = analyze_diff(
				string_before[index_start_before + i],
				string_after[index_start_after + i],
			)

			diff.append(operation_dict)

	return diff