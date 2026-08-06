from collections import Counter

from workspace.evals.generate_zhuyin_dataset import choose_candidate
from workspace.evals.generate_zhuyin_dataset import collect_sentence_options
from workspace.evals.generate_zhuyin_dataset import generate_cases
from workspace.evals.generate_zhuyin_dataset import rank_candidates


def test_rank_candidates_prefers_more_frequent_characters():
	pronunciation_to_chars = {"ㄕˋ": ["世", "市", "是"]}
	char_frequency = Counter({"是": 5, "市": 2, "世": 1})

	ranked = rank_candidates("世", "ㄕˋ", pronunciation_to_chars, char_frequency)

	assert ranked == ["是", "市"]


def test_choose_candidate_top1_returns_first_ranked_item():
	chosen, rank = choose_candidate(["是", "市"], "top1", __import__("random").Random(0))

	assert chosen == "是"
	assert rank == 1


def test_generate_cases_replaces_first_available_character():
	sentences = ["世界和平"]
	char_to_pronunciations = {"世": ["ㄕˋ"], "界": ["ㄐㄧㄝˋ"]}
	pronunciation_to_chars = {"ㄕˋ": ["世", "是"], "ㄐㄧㄝˋ": ["借", "界"]}
	char_frequency = Counter({"是": 10, "借": 1})

	cases = generate_cases(
		sentences=sentences,
		char_to_pronunciations=char_to_pronunciations,
		pronunciation_to_chars=pronunciation_to_chars,
		char_frequency=char_frequency,
		selection="top1",
		seed=0,
	)

	assert len(cases) == 1
	assert cases[0].input_text == "是界和平"
	assert cases[0].expected_text == "世界和平"
	assert cases[0].source_char == "世"
	assert cases[0].target_char == "是"


def test_collect_sentence_options_limits_candidates_per_character():
	options = collect_sentence_options(
		sentence="世界",
		char_to_pronunciations={"世": ["ㄕˋ"]},
		pronunciation_to_chars={"ㄕˋ": ["世", "是", "市", "事"]},
		char_frequency=Counter({"是": 9, "市": 8, "事": 7}),
		selection="top1",
		rng=__import__("random").Random(0),
		max_candidates_per_char=2,
	)

	assert len(options) == 1
	assert options[0].target_char == "是"


def test_generate_cases_can_inject_multiple_errors():
	cases = generate_cases(
		sentences=["世界和平"],
		char_to_pronunciations={"世": ["ㄕˋ"], "界": ["ㄐㄧㄝˋ"]},
		pronunciation_to_chars={"ㄕˋ": ["世", "是"], "ㄐㄧㄝˋ": ["借", "界"]},
		char_frequency=Counter({"是": 10, "借": 9}),
		selection="top1",
		seed=0,
		errors_per_sentence=2,
	)

	assert len(cases) == 1
	assert cases[0].input_text == "是借和平"
	assert cases[0].source_char == "世|界"
	assert cases[0].target_char == "是|借"
