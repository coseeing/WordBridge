import sys
import types
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "addon" / "globalPlugins" / "WordBridge"
sys.path.insert(0, str(ADDON_PATH))

addon_handler = types.ModuleType("addonHandler")
addon_handler.initTranslation = lambda: None
sys.modules.setdefault("addonHandler", addon_handler)


class _Result:
	def __init__(self, output_text):
		self.output_text = output_text


class _FakeExecutor:
	"""Records every execute() call and answers from a scripted responder."""

	def __init__(self, responder):
		self._responder = responder
		self.calls = []

	def ensure_connection(self):
		pass

	def execute(self, input_text, prompt_strategy, text_policy, previous_results=None):
		self.calls.append((input_text, tuple(previous_results or ())))
		return _Result(self._responder(input_text))

	def get_total_usage(self):
		return {}

	def get_total_cost(self):
		return 0

	def get_execution_metrics(self):
		return []


def _script_workflow(monkeypatch, *, segmentations, revisions, responder):
	"""Drive the loop with scripted segmentation and error detection.

	segmentations: one list of segments per text_segmentation() call, the
	first being the initial split.
	revisions: one (revised_text, typo_indices) pair per round; the loop stops
	when revised_text equals the text it was given.
	"""
	from lib.tasks.typo import workflow as workflow_module

	segmentation_iter = iter(segmentations)
	revision_iter = iter(revisions)

	monkeypatch.setattr(
		workflow_module, "text_segmentation", lambda text, max_length=100: next(segmentation_iter)
	)
	monkeypatch.setattr(
		workflow_module, "find_correction_errors", lambda text, corrected: next(revision_iter)
	)
	monkeypatch.setattr(
		workflow_module, "get_segments_to_recorrect", lambda segments, typo_indices: list(segments)
	)
	monkeypatch.setattr(
		workflow_module, "review_correction_errors", lambda text, corrected: corrected
	)
	monkeypatch.setattr(workflow_module, "strings_diff", lambda before, after: [])

	executor = _FakeExecutor(responder)
	workflow = workflow_module.TypoCorrectionWorkflow(
		executor=executor,
		prompt_strategy=object(),
		text_policy=object(),
	)
	return workflow, executor


def test_segment_count_growing_between_rounds_does_not_crash(monkeypatch):
	workflow, executor = _script_workflow(
		monkeypatch,
		segmentations=[
			["甲乙丙"],
			["甲", "乙", "丙"],
			["甲", "乙", "丙", "丁"],
			["甲", "乙", "丙", "丁"],
		],
		revisions=[
			("R1", []),
			("R2", []),
			("R2", []),
		],
		responder=lambda segment: segment + "!",
	)

	result = workflow.run("甲乙丙", batch_mode=True)

	assert result.corrected_text == "甲!乙!丙!丁!"


def test_shrinking_segment_count_does_not_misroute_history(monkeypatch):
	workflow, executor = _script_workflow(
		monkeypatch,
		segmentations=[
			["甲乙丙丁"],
			["甲", "乙", "丙", "丁"],
			["乙", "甲"],
			["乙", "甲"],
		],
		revisions=[
			("R1", []),
			("R2", []),
			("R3", []),
			("R3", []),
		],
		responder=lambda segment: segment + "!",
	)

	workflow.run("甲乙丙丁", batch_mode=False)

	# Round 2 asks about 乙 first and 甲 second. Each must receive the history
	# recorded for its own text in round 1, not the history at its index.
	round_two = executor.calls[5:7]
	assert round_two == [("乙", ("乙!",)), ("甲", ("甲!",))]


def test_equal_count_with_shifted_boundaries_carries_no_stale_history(monkeypatch):
	workflow, executor = _script_workflow(
		monkeypatch,
		segmentations=[
			["甲乙丙丁"],
			["甲乙", "丙丁"],
			["甲", "乙丙丁"],
			["甲", "乙丙丁"],
		],
		revisions=[
			("R1", []),
			("R2", []),
			("R3", []),
			("R3", []),
		],
		responder=lambda segment: segment + "!",
	)

	workflow.run("甲乙丙丁", batch_mode=False)

	round_two = executor.calls[3:5]
	assert round_two == [("甲", ()), ("乙丙丁", ())]


def test_no_recorrection_needed_makes_no_extra_calls(monkeypatch):
	workflow, executor = _script_workflow(
		monkeypatch,
		segmentations=[["甲乙"]],
		# Must echo the initial pass's stitched output ("甲乙" + "!" == "甲乙!") so the
		# loop's break check (text_corrected_revised == text_corrected) fires on the
		# first iteration. Do not "fix" this back to "甲!乙!" — the initial segmentation
		# is a single segment, so only one "!" is ever appended.
		revisions=[("甲乙!", [])],
		responder=lambda segment: segment + "!",
	)

	result = workflow.run("甲乙", batch_mode=True)

	assert result.corrected_text == "甲乙!"
	assert len(executor.calls) == 1


def test_empty_result_falls_back_to_the_segment_text(monkeypatch):
	workflow, executor = _script_workflow(
		monkeypatch,
		segmentations=[
			["甲乙"],
			["甲", "乙"],
			["甲", "乙"],
			["甲", "乙"],
		],
		revisions=[
			("R1", []),
			("R2", []),
			("R2", []),
		],
		responder=lambda segment: "" if segment == "乙" else segment + "!",
	)

	result = workflow.run("甲乙", batch_mode=True)

	assert result.corrected_text == "甲!乙"


def test_parallel_map_rejects_mismatched_kwargs_length():
	from lib.tasks.concurrency import parallel_map

	with pytest.raises(ValueError):
		parallel_map(lambda item, previous_results=None: item, ["a", "b", "c"], iterable_kwargs=[{}])
