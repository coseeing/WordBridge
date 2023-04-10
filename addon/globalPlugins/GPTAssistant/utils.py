from difflib import SequenceMatcher
from typing import Dict


# from chinese_dictionary import pronouce_to_chars_dict, char_to_pronouces_dict

SEPERATOR = "﹐，,.。﹒．｡:։׃∶˸︓﹕：!ǃⵑ︕！;;︔﹔；?︖﹖？⋯ \n\r\t"


def rstrip_seperator(string: str) -> str:
	return string.rstrip(SEPERATOR)


def text_segmentation(text: str, max_length: int = 50) -> list:
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

	word = ""
	for char in text:
		word += char
		if char in SEPERATOR or len(word) >= max_length:
			if word:
				partitions.append(word)
			word = ""

	if word:
		partitions.append(word)

	return partitions


def strings_diff(string1: str, string2: str) -> Dict:

	# operation is replace or insert or delete

	matcher = SequenceMatcher(None, string1, string2)
	diff = []
	for tag, index_start1, index_end1, index_start2, index_end2 in matcher.get_opcodes():
		if tag == "equal":
			continue

		operation_dict = {
			"operation": tag,
			"index_start1": index_start1,
			"index_end1": index_end1,
			"index_start2": index_start2,
			"index_end2": index_end2,
		}

		diff.append(operation_dict)

	return diff
