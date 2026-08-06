import argparse
import csv
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = PROJECT_ROOT / "workspace" / "evals" / "datasets" / "gpt4_250_sentence_gt.txt"
DEFAULT_OUTPUT = PROJECT_ROOT / "workspace" / "evals" / "datasets" / "zhuyin_1_error_top1_seed0.csv"
DEFAULT_DICTIONARY = (
	PROJECT_ROOT
	/ "addon"
	/ "globalPlugins"
	/ "WordBridge"
	/ "lib"
	/ "tasks"
	/ "typo"
	/ "data"
	/ "chinese_dictionary_bopomofo.csv"
)


def is_cjk_character(char: str) -> bool:
	return "\u4e00" <= char <= "\u9fff"


def normalize_pronunciation(value: str) -> str:
	return value.strip().replace(" ", "")


@dataclass(frozen=True)
class CandidateCase:
	input_text: str
	expected_text: str
	source_char: str
	target_char: str
	pronunciation: str
	candidate_rank: str
	sentence_id: int
	error_type: str = "zhuyin_top1_homophone"


class CandidateOption(NamedTuple):
	index: int
	source_char: str
	target_char: str
	pronunciation: str
	candidate_rank: int


def load_sentences(path: Path) -> list[str]:
	if path.suffix.lower() == ".csv":
		with path.open(encoding="utf8", newline="") as csvfile:
			reader = csv.DictReader(csvfile)
			if reader.fieldnames is None:
				raise ValueError(f"CSV source has no header: {path}")
			expected_key = "expected" if "expected" in reader.fieldnames else "input"
			sentences = [row[expected_key].strip() for row in reader if row.get(expected_key, "").strip()]
	else:
		with path.open(encoding="utf8") as textfile:
			sentences = [line.strip() for line in textfile if line.strip()]

	if not sentences:
		raise ValueError(f"No sentences loaded from {path}")
	return sentences


def build_char_frequency(sentences: list[str]) -> Counter[str]:
	counter: Counter[str] = Counter()
	for sentence in sentences:
		for char in sentence:
			if is_cjk_character(char):
				counter[char] += 1
	return counter


def load_bopomofo_mappings(path: Path) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
	char_to_pronunciations: defaultdict[str, set[str]] = defaultdict(set)
	pronunciation_to_chars: defaultdict[str, set[str]] = defaultdict(set)

	with path.open(encoding="utf8", newline="") as csvfile:
		reader = csv.reader(csvfile)
		next(reader, None)
		for row in reader:
			if len(row) < 3:
				continue
			traditional_char = row[0].strip()
			pronunciation = normalize_pronunciation(row[2])
			if len(traditional_char) != 1 or not is_cjk_character(traditional_char):
				continue
			if not pronunciation:
				continue
			char_to_pronunciations[traditional_char].add(pronunciation)
			pronunciation_to_chars[pronunciation].add(traditional_char)

	char_map = {
		char: sorted(pronunciations)
		for char, pronunciations in char_to_pronunciations.items()
	}
	pronunciation_map = {
		pronunciation: sorted(chars)
		for pronunciation, chars in pronunciation_to_chars.items()
	}
	return char_map, pronunciation_map


def rank_candidates(
	source_char: str,
	pronunciation: str,
	pronunciation_to_chars: dict[str, list[str]],
	char_frequency: Counter[str],
) -> list[str]:
	candidates = [
		candidate
		for candidate in pronunciation_to_chars.get(pronunciation, [])
		if candidate != source_char
	]
	return sorted(
		candidates,
		key=lambda candidate: (-char_frequency[candidate], candidate),
	)


def choose_candidate(ranked_candidates: list[str], selection: str, rng: random.Random) -> tuple[str, int]:
	if not ranked_candidates:
		raise ValueError("ranked_candidates must not be empty")

	if selection == "top1":
		return ranked_candidates[0], 1

	weights = [max(len(ranked_candidates) - index, 1) for index in range(len(ranked_candidates))]
	chosen_index = rng.choices(range(len(ranked_candidates)), weights=weights, k=1)[0]
	return ranked_candidates[chosen_index], chosen_index + 1


def collect_sentence_options(
	sentence: str,
	char_to_pronunciations: dict[str, list[str]],
	pronunciation_to_chars: dict[str, list[str]],
	char_frequency: Counter[str],
	selection: str,
	rng: random.Random,
	max_candidates_per_char: int,
) -> list[CandidateOption]:
	options: list[CandidateOption] = []
	for index, char in enumerate(sentence):
		if char not in char_to_pronunciations:
			continue
		for pronunciation in char_to_pronunciations[char]:
			ranked_candidates = rank_candidates(
				source_char=char,
				pronunciation=pronunciation,
				pronunciation_to_chars=pronunciation_to_chars,
				char_frequency=char_frequency,
			)
			if max_candidates_per_char > 0:
				ranked_candidates = ranked_candidates[:max_candidates_per_char]
			if not ranked_candidates:
				continue
			target_char, candidate_rank = choose_candidate(ranked_candidates, selection, rng)
			if target_char == char:
				continue
			options.append(
				CandidateOption(
					index=index,
					source_char=char,
					target_char=target_char,
					pronunciation=pronunciation,
					candidate_rank=candidate_rank,
				)
			)
	return options


def generate_cases(
	sentences: list[str],
	char_to_pronunciations: dict[str, list[str]],
	pronunciation_to_chars: dict[str, list[str]],
	char_frequency: Counter[str],
	selection: str,
	seed: int,
	max_candidates_per_char: int = 3,
	max_pair_ratio: float = 0.05,
	errors_per_sentence: int = 1,
) -> list[CandidateCase]:
	rng = random.Random(seed)
	cases: list[CandidateCase] = []
	pair_counter: Counter[tuple[str, str]] = Counter()
	max_pair_count = max(1, int(len(sentences) * max_pair_ratio))

	for sentence_id, sentence in enumerate(sentences, start=1):
		options = collect_sentence_options(
			sentence=sentence,
			char_to_pronunciations=char_to_pronunciations,
			pronunciation_to_chars=pronunciation_to_chars,
			char_frequency=char_frequency,
			selection=selection,
			rng=rng,
			max_candidates_per_char=max_candidates_per_char,
		)
		if not options:
			continue

		rng.shuffle(options)
		options.sort(key=lambda option: (pair_counter[(option.source_char, option.target_char)], option.candidate_rank))

		chosen_options: list[CandidateOption] = []
		used_indices: set[int] = set()
		for option in options:
			pair = (option.source_char, option.target_char)
			if option.index in used_indices:
				continue
			if pair_counter[pair] >= max_pair_count:
				continue
			chosen_options.append(option)
			used_indices.add(option.index)
			if len(chosen_options) >= errors_per_sentence:
				break

		if not chosen_options:
			for option in options:
				if option.index in used_indices:
					continue
				chosen_options.append(option)
				used_indices.add(option.index)
				if len(chosen_options) >= errors_per_sentence:
					break

		if not chosen_options:
			continue

		mutated_chars = list(sentence)
		source_chars: list[str] = []
		target_chars: list[str] = []
		pronunciations: list[str] = []
		candidate_ranks: list[str] = []
		for option in sorted(chosen_options, key=lambda item: item.index):
			mutated_chars[option.index] = option.target_char
			source_chars.append(option.source_char)
			target_chars.append(option.target_char)
			pronunciations.append(option.pronunciation)
			candidate_ranks.append(str(option.candidate_rank))
			pair_counter[(option.source_char, option.target_char)] += 1

		input_text = "".join(mutated_chars)
		if input_text == sentence:
			continue
		cases.append(
			CandidateCase(
				input_text=input_text,
				expected_text=sentence,
				source_char="|".join(source_chars),
				target_char="|".join(target_chars),
				pronunciation="|".join(pronunciations),
				candidate_rank="|".join(candidate_ranks),
				sentence_id=sentence_id,
				error_type="zhuyin_homophone_sentence",
			)
		)

	return cases


def write_promptfoo_csv(path: Path, cases: list[CandidateCase], f2_threshold: float, ned_threshold: float) -> None:
	with path.open("w", encoding="utf8", newline="") as csvfile:
		writer = csv.DictWriter(
			csvfile,
			fieldnames=["input", "expected", "f2_threshold", "ned_threshold"],
		)
		writer.writeheader()
		for case in cases:
			writer.writerow(
				{
					"input": case.input_text,
					"expected": case.expected_text,
					"f2_threshold": f2_threshold,
					"ned_threshold": ned_threshold,
				}
			)


def write_rich_csv(path: Path, cases: list[CandidateCase], f2_threshold: float, ned_threshold: float) -> None:
	with path.open("w", encoding="utf8", newline="") as csvfile:
		writer = csv.DictWriter(
			csvfile,
			fieldnames=[
				"input",
				"expected",
				"error_type",
				"source_char",
				"target_char",
				"pronunciation",
				"candidate_rank",
				"sentence_id",
				"f2_threshold",
				"ned_threshold",
			],
		)
		writer.writeheader()
		for case in cases:
			writer.writerow(
				{
					"input": case.input_text,
					"expected": case.expected_text,
					"error_type": case.error_type,
					"source_char": case.source_char,
					"target_char": case.target_char,
					"pronunciation": case.pronunciation,
					"candidate_rank": case.candidate_rank,
					"sentence_id": case.sentence_id,
					"f2_threshold": f2_threshold,
					"ned_threshold": ned_threshold,
				}
			)


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Generate a WordBridge eval dataset based on Zhuyin homophone substitutions."
	)
	parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Text or CSV file of clean sentences.")
	parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output CSV path.")
	parser.add_argument(
		"--dictionary",
		type=Path,
		default=DEFAULT_DICTIONARY,
		help="Bopomofo dictionary CSV.",
	)
	parser.add_argument(
		"--selection",
		choices=["top1", "weighted"],
		default="top1",
		help="How to choose a candidate from ranked same-pronunciation characters.",
	)
	parser.add_argument(
		"--format",
		choices=["promptfoo", "rich"],
		default="promptfoo",
		help="Output schema.",
	)
	parser.add_argument("--seed", type=int, default=0, help="Random seed for weighted selection.")
	parser.add_argument("--limit", type=int, default=0, help="Limit the number of output rows. 0 means no limit.")
	parser.add_argument("--f2-threshold", type=float, default=0.8, help="Default F2 threshold written to CSV.")
	parser.add_argument("--ned-threshold", type=float, default=0.1, help="Default NED threshold written to CSV.")
	parser.add_argument(
		"--max-candidates-per-char",
		type=int,
		default=3,
		help="Only consider the top-K frequency-ranked candidates for each source character.",
	)
	parser.add_argument(
		"--max-pair-ratio",
		type=float,
		default=0.05,
		help="Approximate upper bound for how much a single source->target pair can dominate the dataset.",
	)
	parser.add_argument(
		"--errors-per-sentence",
		type=int,
		default=1,
		help="How many typos to inject per sentence.",
	)
	return parser.parse_args()


def main() -> None:
	args = parse_args()
	sentences = load_sentences(args.source)
	char_frequency = build_char_frequency(sentences)
	char_to_pronunciations, pronunciation_to_chars = load_bopomofo_mappings(args.dictionary)
	cases = generate_cases(
		sentences=sentences,
		char_to_pronunciations=char_to_pronunciations,
		pronunciation_to_chars=pronunciation_to_chars,
		char_frequency=char_frequency,
		selection=args.selection,
		seed=args.seed,
		max_candidates_per_char=args.max_candidates_per_char,
		max_pair_ratio=args.max_pair_ratio,
		errors_per_sentence=args.errors_per_sentence,
	)

	if args.limit > 0:
		cases = cases[:args.limit]

	args.output.parent.mkdir(parents=True, exist_ok=True)
	if args.format == "promptfoo":
		write_promptfoo_csv(args.output, cases, args.f2_threshold, args.ned_threshold)
	else:
		write_rich_csv(args.output, cases, args.f2_threshold, args.ned_threshold)

	print(f"Generated {len(cases)} cases at {args.output}")


if __name__ == "__main__":
	main()
