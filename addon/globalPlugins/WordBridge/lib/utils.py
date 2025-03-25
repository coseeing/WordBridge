import random

from difflib import SequenceMatcher
from typing import Dict, List
from chinese_converter import to_simplified, to_traditional
from .chinese_dictionary import string_to_pinyin, pinyin_to_string
from hanzidentifier import identify
from hanzidentifier import MIXED, SIMPLIFIED, TRADITIONAL
from pypinyin import pinyin

try:
	from languageHandler import getLanguage
	from speech.speech import getCharDescListFromText
except ImportError:
	getLanguage = None
	getCharDescListFromText = None

# Characters used for text segmentation
SEPERATOR = "﹐，,.。﹒．｡!ǃⵑ︕！;;︔﹔；?︖﹖？⋯ "
PUNCTUATION = "﹐，,.。﹒．｡:։׃∶˸︓﹕：!ǃⵑ︕！;;︔﹔；?︖﹖？⋯ \n\r\t\"\'#$%&()*+-/<=>@[\]^_`{|}~"

ZH_UNICODE_INTERVALS = [
	["\u4e00", "\u9fff"],
	["\u3400", "\u4dbf"],
	["\u20000", "\u2a6df"],
	["\u2a700", "\u2b739"],
	["\u2b740", "\u2b81d"],
	["\u2b820", "\u2cea1"],
	["\u2ceb0", "\u2ebe0"],
	["\u30000", "\u3134a"],
	["\u31350", "\u323af"],
	["\u3100", "\u312f"],
	["\u31a0", "\u31bf"],
	["\uf900", "\ufaff"],
	["\u2f800", "\u2fa1f"],
]


def is_chinese_character(char: str) -> bool:
	assert len(char) == 1, "Length of char should be 1."
	for interval in ZH_UNICODE_INTERVALS:
		if char >= interval[0] and char <= interval[1]:
			return True

	return False


def has_chinese(text: str):
	for char in text:
		if is_chinese_character(char):
			return True
	return False


def get_char_pinyin(char: str) -> List:
	assert len(char) == 1, "Length of char should be 1."
	pinyins_set = set(string_to_pinyin[char]) | set(pinyin(char, heteronym=True)[0])
	return list(pinyins_set)


def typo_augmentation(text: str, is_traditional: bool, error_rate: float = 0.125) -> str:
	if not is_traditional:
		text = to_traditional(text)

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


def tokenizer(text):
	tokens = []
	token = ""
	for char in text:
		if not (char in PUNCTUATION or is_chinese_character(char)):
			token += char
			continue

		if token:
			tokens.append(token)
			token = ""
		tokens.append(char)

	if token:
		tokens.append(token)

	return tokens


def create_single_char_mapping(tokens):
	assert len(tokens) <= 20000

	mapping = {}
	chinese_char = 19968  # map each token to a Chinese character
	for t in set(tokens):
		if t in mapping:
			continue
		mapping[t] = chr(chinese_char)
		chinese_char += 1

	return mapping


def create_encode_string(tokens, mapping):
	return "".join([mapping[t] for t in tokens])


def text_segmentation(text: str, max_length: int = 30) -> tuple:
	"""
	This function can be used to split a string into substrings based on a set of specified separators or
	a maximum length limit.

	Parameters:
		text (str): A string that needs to be partitioned into substrings based on certain separators or
					a maximum length limit.
		max_length (int): The maximum length of each substring. If a substring reaches this length, it will be
							partitioned at the next separator encountered.
	Returns:
		A list of substrings.
	"""

	partitions = []

	word = ""
	for char in text:
		word += char

		if char in SEPERATOR and len(word) >= max_length:
			partitions.append(word)
			word = ""

	if not word:
		return partitions

	if not partitions or len(word) > max_length / 2:
		partitions.append(word)
	else:
		partitions[-1] += word

	return partitions


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
	if len(char_original) != 1 or len(char_corrected) != 1:
		return ["Correction for non-Chinese case"]

	tags = []

	# char_simplified = to_simplified(char_original)
	# char_traditional = to_traditional(char_original)
	char_simplified = char_original
	char_traditional = char_original
	if char_original != char_simplified and char_simplified == char_corrected:
		tags.append("Tranditional to simplified")
	elif char_original != char_traditional and char_traditional == char_corrected:
		tags.append("Simplified to tranditional")

	if set(string_to_pinyin[char_original]) & set(string_to_pinyin[char_corrected]):
		tags.append("Share the same pronunciation")
	else:
		tags.append("Do not share the same pronunciation")

	return tags


def has_simplified_chinese_char(text: str):
	return identify(text) in [SIMPLIFIED, MIXED]


def has_traditional_chinese_char(text: str):
	return identify(text) in [TRADITIONAL, MIXED]


def find_correction_errors(text, text_corrected):
	differences = strings_diff(text, text_corrected)
	text_corrected_fixed = ""
	typo_indices = []
	for diff in differences:
		if diff["operation"] in ["insert", "delete"]:  # Insert or delete
			text_corrected_fixed += diff["before_text"]
			typo_indices.append(max(len(text_corrected_fixed) - 1, 0))
			continue

		share_common_pinyin = True
		for before_char, after_char in zip(diff["before_text"], diff["after_text"]):
			if len(set(get_char_pinyin(before_char)) & set(get_char_pinyin(after_char))) == 0:
				share_common_pinyin = False
				break

		if share_common_pinyin:
			text_corrected_fixed += diff["after_text"]
		else:
			text_corrected_fixed += diff["before_text"]
			typo_indices.extend(
				list(range(len(text_corrected_fixed) - len(diff["after_text"]), len(text_corrected_fixed)))
			)

	return text_corrected_fixed, typo_indices


def review_correction_errors(text, text_corrected):
	differences = strings_diff(text, text_corrected)
	text_corrected_fixed = ""
	typo_indices = []
	for diff in differences:
		if diff["operation"] in ["insert", "delete"]:  # Insert or delete
			text_corrected_fixed += diff["before_text"]
			continue

		if diff["before_text"] and not all(is_chinese_character(c) for c in diff["before_text"]):
			text_corrected_fixed += diff["before_text"]
		elif diff["after_text"] and not all(is_chinese_character(c) for c in diff["after_text"]):
			text_corrected_fixed += diff["before_text"]
		else:
			text_corrected_fixed += diff["after_text"]

	return text_corrected_fixed


def get_segments_to_recorrect(segments: list, typo_indices: list, max_length: int = 30) -> tuple:
	text = "".join(segments)
	segments_to_correct = []
	index_start = 0
	index_end = 0
	for k in range(len(segments)):
		is_error = False
		index_end += len(segments[k])
		text_with_tag = ""
		for j in range(index_start, index_end):
			if j in typo_indices:
				is_error = True
				text_with_tag += ("[[" + text[j] + "]]")
			else:
				text_with_tag += text[j]
		if is_error:
			segments_to_correct.append(text_with_tag)
		else:
			segments_to_correct.append("")
		index_start = index_end

	return segments_to_correct


def get_descs(text: str) -> str:
	if not text or getLanguage is None or getCharDescListFromText is None:
		return ""

	if len(text) > 1:  # For non-Chinese character or word
		return [[text, [" ".join(list(text))]]]

	return getCharDescListFromText(text, getLanguage())


def strings_diff(string_before: str, string_after: str) -> Dict:

	tokens_before = tokenizer(string_before)
	tokens_after = tokenizer(string_after)

	mapping = create_single_char_mapping(tokens_before + tokens_after)
	string_before_encode = create_encode_string(tokens_before, mapping)
	string_after_encode = create_encode_string(tokens_after, mapping)

	matcher = SequenceMatcher(None, string_before_encode, string_after_encode)

	# Postprocess the op codes
	matcher_ops = []
	for op, index_start_before, index_end_before, index_start_after, index_end_after in matcher.get_opcodes():
		if op != "replace" or (index_end_before - index_start_before) == (index_end_after - index_start_after):
			matcher_ops.append((op, index_start_before, index_end_before, index_start_after, index_end_after))
		elif index_end_before - index_start_before < index_end_after - index_start_after:
			index_middle = index_start_after + (index_end_before - index_start_before)
			matcher_ops.append(("replace", index_start_before, index_end_before, index_start_after, index_middle))
			matcher_ops.append(("insert", index_end_before, index_end_before, index_middle, index_end_after))
		else:
			index_middle = index_start_before + (index_end_after - index_start_after)
			matcher_ops.append(("replace", index_start_before, index_middle, index_start_after, index_end_after))
			matcher_ops.append(("delete", index_middle, index_end_before, index_end_after, index_end_after))

	# operation (op) is replace or insert or delete
	diff = []
	for op, index_start_before, index_end_before, index_start_after, index_end_after in matcher_ops:
		if op == "equal":
			operation_dict = {
				"operation": op,
				"before_text": "".join(tokens_before[index_start_before:index_end_before]),
				"after_text": "".join(tokens_after[index_start_after:index_end_after]),
				"before_descs": "",
				"after_descs": "",
				"tags": None,
			}
			diff.append(operation_dict)
			continue
		elif op != "replace":
			operation_dict = {
				"operation": op,
				"before_text": "".join(tokens_before[index_start_before:index_end_before]),
				"after_text": "".join(tokens_after[index_start_after:index_end_after]),
				"before_descs": get_descs("".join(tokens_before[index_start_before:index_end_before])),
				"after_descs": get_descs("".join(tokens_after[index_start_after:index_end_after])),
				"tags": None,
			}
			diff.append(operation_dict)
			continue

		for i in range(index_end_before - index_start_before):
			operation_dict = {
				"operation": op,
				"before_text": "".join(tokens_before[(index_start_before + i):(index_start_before + i + 1)]),
				"after_text": "".join(tokens_after[(index_start_after + i):(index_start_after + i + 1)]),
				"before_descs": get_descs("".join(tokens_before[(index_start_before + i):(index_start_before + i + 1)])),
				"after_descs": get_descs("".join(tokens_after[(index_start_after + i):(index_start_after + i + 1)])),
				"tags": None,
			}
			operation_dict["tags"] = analyze_diff(
				"".join(tokens_before[index_start_before + i]),
				"".join(tokens_after[index_start_after + i]),
			)

			diff.append(operation_dict)

	return diff
