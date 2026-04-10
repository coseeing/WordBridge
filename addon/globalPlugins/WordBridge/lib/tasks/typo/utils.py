import random

from difflib import SequenceMatcher
from chinese_converter import to_simplified, to_traditional
from pypinyin import pinyin

from ...text.chinese import (
	PUNCTUATION,
	get_descs,
	is_chinese_character,
)
from .chinese_dictionary import pinyin_to_string, string_to_pinyin


def get_char_pinyin(char: str) -> list:
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
	chinese_char = 19968
	for token in set(tokens):
		if token in mapping:
			continue
		mapping[token] = chr(chinese_char)
		chinese_char += 1

	return mapping


def create_encode_string(tokens, mapping):
	return "".join([mapping[token] for token in tokens])


def text_segmentation(text: str, max_length: int = 30) -> tuple:
	partitions = []
	word = ""
	for char in text:
		word += char

		if char in PUNCTUATION and len(word) >= max_length:
			partitions.append(word)
			word = ""

	if not word:
		return partitions

	if not partitions or len(word) > max_length / 2:
		partitions.append(word)
	else:
		partitions[-1] += word

	return partitions


def analyze_diff(char_original: str, char_corrected: str) -> list:
	if len(char_original) != 1 or len(char_corrected) != 1:
		return ["Correction for non-Chinese case"]

	tags = []
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


def strings_diff(string_before: str, string_after: str) -> dict:
	tokens_before = tokenizer(string_before)
	tokens_after = tokenizer(string_after)

	mapping = create_single_char_mapping(tokens_before + tokens_after)
	string_before_encode = create_encode_string(tokens_before, mapping)
	string_after_encode = create_encode_string(tokens_after, mapping)
	matcher = SequenceMatcher(None, string_before_encode, string_after_encode)

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

	diff = []
	for op, index_start_before, index_end_before, index_start_after, index_end_after in matcher_ops:
		if op == "equal":
			diff.append(
				{
					"operation": op,
					"before_text": "".join(tokens_before[index_start_before:index_end_before]),
					"after_text": "".join(tokens_after[index_start_after:index_end_after]),
					"before_descs": "",
					"after_descs": "",
					"tags": None,
				}
			)
			continue
		if op != "replace":
			diff.append(
				{
					"operation": op,
					"before_text": "".join(tokens_before[index_start_before:index_end_before]),
					"after_text": "".join(tokens_after[index_start_after:index_end_after]),
					"before_descs": get_descs("".join(tokens_before[index_start_before:index_end_before])),
					"after_descs": get_descs("".join(tokens_after[index_start_after:index_end_after])),
					"tags": None,
				}
			)
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
			assert len(operation_dict["before_text"]) == 1 and len(operation_dict["after_text"]) == 1
			diff.append(operation_dict)

	return diff


def find_correction_errors(text, text_corrected):
	differences = strings_diff(text, text_corrected)
	text_corrected_fixed = ""
	typo_indices = []
	for diff in differences:
		if diff["operation"] == "equal":
			text_corrected_fixed += diff["after_text"]
			continue
		if diff["operation"] in ["insert", "delete"]:
			text_corrected_fixed += diff["before_text"]
			typo_indices.append(max(len(text_corrected_fixed) - 1, 0))
			continue

		if len(set(get_char_pinyin(diff["before_text"])) & set(get_char_pinyin(diff["after_text"]))) == 0:
			text_corrected_fixed += diff["before_text"]
			typo_indices.append(len(text_corrected_fixed) - 1)
		else:
			text_corrected_fixed += diff["after_text"]

	return text_corrected_fixed, typo_indices


def review_correction_errors(text, text_corrected):
	differences = strings_diff(text, text_corrected)
	text_corrected_fixed = ""
	for diff in differences:
		if diff["operation"] != "replace":
			text_corrected_fixed += diff["before_text"]
			continue

		if is_chinese_character(diff["before_text"]) and is_chinese_character(diff["after_text"]):
			text_corrected_fixed += diff["after_text"]
		else:
			text_corrected_fixed += diff["before_text"]

	return text_corrected_fixed


def get_segments_to_recorrect(segments: list, typo_indices: list, max_length: int = 30) -> tuple:
	text = "".join(segments)
	segments_to_correct = []
	index_start = 0
	index_end = 0
	for segment in segments:
		is_error = False
		index_end += len(segment)
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
