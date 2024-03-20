from copy import deepcopy
from typing import Dict
from pypinyin import pinyin

from chinese_dictionary import pinyin_to_string, string_to_pinyin, stopwords


def pinyin_custom(text):
	yin = []
	for char in text:
		if char in string_to_pinyin:
			yin.append(string_to_pinyin[char])
		else:
			yin.append(pinyin(char, heteronym=True)[0])
	return yin

def get_string_candidates(text):
	pinyin_candidates = [""]
	for char_pinyins in pinyin_custom(text):
		if len(char_pinyins) == 1:
			pinyin_candidates = [pinyin_candidate + " " + char_pinyins[0] for pinyin_candidate in pinyin_candidates]
			continue

		pinyin_candidates_previous = pinyin_candidates
		pinyin_candidates = []
		for char_pinyin in char_pinyins:
			pinyin_candidates.extend([text + " " + char_pinyin for text in pinyin_candidates_previous])

	pinyin_candidates = [pinyin_candidate.strip() for pinyin_candidate in pinyin_candidates]
	string_candidates = []
	for pinyin_candidate in pinyin_candidates:
		if pinyin_candidate in pinyin_to_string:
			string_candidates.extend(pinyin_to_string[pinyin_candidate])
	
	string_candidates_refine = []
	diff_count = len(text)
	for string_candidate in string_candidates:
		diff = 0
		for i in range(len(text)):
			if text[i] != string_candidate[i]:
				diff += 1
		if diff < diff_count:
			string_candidates_refine = [string_candidate]
			diff_count = diff
		elif diff == diff_count:
			string_candidates_refine.append(string_candidate)

	return string_candidates_refine, diff_count

def segmentation(text: str):
	string_longest = max(list(string_to_pinyin.keys()), key=lambda x: len(x))
	string_max_length = len(string_longest)

	dp = {-1: []}
	cost = {-1: [0, 0, 0]}  # [single_character_count, character_change_count, segment_count]
	for i in range(len(text)):
		dp[i] = None
		cost[i] = [float("inf"), float("inf"), float("inf")]
		for j in range(max(i - string_max_length + 1, 0), i + 1):
			text_sub = text[j:(i + 1)]
			if len(text_sub) > 1:
				string_candidates, character_change_count = get_string_candidates(text_sub)
			else:
				string_candidates, character_change_count = [text_sub], 0

			if not string_candidates:
				continue

			single_character_count_previous = cost[j - 1][0]
			character_change_count_previous = cost[j - 1][1]
			segment_count_previous = cost[j - 1][2]

			cost_i_j_tmp = [
				single_character_count_previous,
				character_change_count_previous,
				segment_count_previous + 1
			]
			if j == i and text_sub not in stopwords:
				cost_i_j_tmp[0] += 1

			if character_change_count is not None:
				cost_i_j_tmp[1] += character_change_count

			if cost_i_j_tmp < cost[i]:
				cost[i] = cost_i_j_tmp
				dp[i] = deepcopy(dp[j - 1])
				dp[i].append(string_candidates)
			elif cost_i_j_tmp == cost[i]:
				pass  # Skip some cases (work around)

	return dp[len(text) - 1]