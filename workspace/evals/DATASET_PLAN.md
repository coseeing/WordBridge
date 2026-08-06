# WordBridge Eval Dataset Plan

## Goal

Build an eval dataset that matches the WordBridge use case more closely than generic Chinese spelling-correction benchmarks:

- Traditional Chinese
- Zhuyin/Bopomofo input
- "No candidate selection" errors
- High-frequency homophone substitutions first

## Dataset Strategy

Use a hybrid approach:

1. Reuse existing clean sentences in the repo as `expected`.
2. Generate `input` by replacing one character with a same-pronunciation candidate.
3. Rank replacement candidates by corpus frequency instead of pure random choice.
4. Keep the dataset distribution healthy by avoiding overuse of one replacement pair.

This keeps the dataset realistic, reproducible, and runnable offline inside the repo.

## First Deliverable

The first generated dataset focuses on one narrow slice:

- sentence-level pairs
- one typo per sentence
- same Zhuyin pronunciation
- top-k high-frequency candidates with weighted sampling
- pair-level repetition cap

This matches the current Promptfoo schema directly:

```csv
input,expected,f2_threshold,ned_threshold
```

## Files

- Generator: [workspace/evals/generate_zhuyin_dataset.py](/Users/simone/side-project/WordBridge/workspace/evals/generate_zhuyin_dataset.py)
- Generated eval dataset: [workspace/evals/datasets/zhuyin_top1_from_legacy.csv](/Users/simone/side-project/WordBridge/workspace/evals/datasets/zhuyin_top1_from_legacy.csv)
- Two-error dataset: [workspace/evals/datasets/zhuyin_two_error_seed0.csv](/Users/simone/side-project/WordBridge/workspace/evals/datasets/zhuyin_two_error_seed0.csv)
- Three-error dataset: [workspace/evals/datasets/zhuyin_three_error_seed0.csv](/Users/simone/side-project/WordBridge/workspace/evals/datasets/zhuyin_three_error_seed0.csv)
- Source corpus: [workspace/eval_legacy/data/gpt4_250_sentence_gt.txt](/Users/simone/side-project/WordBridge/workspace/eval_legacy/data/gpt4_250_sentence_gt.txt)

## Generation Rules

For each source sentence:

1. Find Chinese characters that exist in the bopomofo dictionary.
2. Retrieve all same-pronunciation single-character candidates.
3. Remove the original character from the candidate list.
4. Rank candidates by frequency in the source corpus.
5. Only keep the top-k candidates for each source character.
6. Sample a replacement position from all valid positions in the sentence.
7. Sample a candidate with high-frequency bias.
8. Avoid letting one `source -> target` pair dominate the dataset.
9. Keep only rows where the sentence actually changes.

## Why This Version First

- It is reproducible with a seed.
- It is easy to inspect manually.
- It is close to the "no candidate selection" scenario.
- It plugs into the current eval pipeline without changing assertions or provider code.

## Output Columns

The generator can write two formats:

1. Promptfoo CSV:
   - `input`
   - `expected`
   - `f2_threshold`
   - `ned_threshold`

2. Rich CSV:
   - all Promptfoo fields
   - `error_type`
   - `source_char`
   - `target_char`
   - `pronunciation`
   - `candidate_rank`
   - `sentence_id`

The rich format is useful for analysis and debugging.

## Recommended Next Datasets

After the first dataset is stable, add:

1. `zhuyin_top1_char.csv`
   Single-character confusion pairs.
2. `zhuyin_weighted_sentence.csv`
   Sentence-level data with weighted random candidate selection.
3. `zhuyin_two_error_seed0.csv`
   Sentences with 2 errors for moderate stress testing.
4. `zhuyin_three_error_seed0.csv`
   Sentences with 3 errors for harder stress testing.
5. `manual_hard_cases.csv`
   Curated real-world mistakes collected from testing.

## Commands

Generate the default dataset:

```bash
python workspace/evals/generate_zhuyin_dataset.py
```

Generate a rich CSV:

```bash
python workspace/evals/generate_zhuyin_dataset.py \
  --format rich \
  --output workspace/evals/datasets/zhuyin_top1_from_legacy_rich.csv
```

Generate a weighted-random variant:

```bash
python workspace/evals/generate_zhuyin_dataset.py \
  --selection weighted \
  --seed 7 \
  --output workspace/evals/datasets/zhuyin_weighted_seed7.csv
```

Generate a two-error stress set:

```bash
python workspace/evals/generate_zhuyin_dataset.py \
  --errors-per-sentence 2 \
  --output workspace/evals/datasets/zhuyin_two_error_seed0.csv
```

Generate a three-error stress set:

```bash
python workspace/evals/generate_zhuyin_dataset.py \
  --errors-per-sentence 3 \
  --output workspace/evals/datasets/zhuyin_three_error_seed0.csv
```

Run the dataset unit tests with the repo venv:

```bash
venv/bin/python -m pytest -q tests/test_generate_zhuyin_dataset_unittest.py
```

Run Promptfoo by difficulty:

```bash
promptfoo eval -c workspace/evals/promptfooconfig.single.yaml
promptfoo eval -c workspace/evals/promptfooconfig.double.yaml
promptfoo eval -c workspace/evals/promptfooconfig.triple.yaml
```

Run the combined benchmark:

```bash
promptfoo eval -c workspace/evals/promptfooconfig.yaml
```
