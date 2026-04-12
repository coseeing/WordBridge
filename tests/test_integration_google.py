import pytest
from test_helpers import (
	build_typo_workflow_for_provider,
	print_test_results,
	run_workflow_or_skip_transient_failure,
)

PROVIDER_NAME = "Google"
MODELS_TO_TEST = [
	"gemini-2.5-flash",
	"gemini-2.5-flash-lite",
]


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("model_name", MODELS_TO_TEST)
def test_gemini_basic_correction(model_config, credentials, test_data, model_name):
	workflow = build_typo_workflow_for_provider(
		provider_name=PROVIDER_NAME,
		model_name=model_name,
		model_config=model_config,
		credentials=credentials,
	)

	test_text = test_data["basic_text"]
	result = run_workflow_or_skip_transient_failure(workflow, test_text, batch_mode=True)
	response, diff = result.corrected_text, result.diff

	assert response is not None, "Response should not be None"
	assert isinstance(response, str), "Response should be a string"
	assert isinstance(diff, list), "Diff should be a list"

	cost = workflow.executor.get_total_cost()
	assert cost > 0, "Cost should be positive when usage is returned"

	assert len(workflow.executor.response_history) > 0, "Should have response history"

	print_test_results(model_name, test_text, response, diff, workflow.executor)


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("model_name", MODELS_TO_TEST)
def test_gemini_with_typo(model_config, credentials, test_data, model_name):
	workflow = build_typo_workflow_for_provider(
		provider_name=PROVIDER_NAME,
		model_name=model_name,
		model_config=model_config,
		credentials=credentials,
	)

	test_text = test_data["text_with_typo"]
	result = run_workflow_or_skip_transient_failure(workflow, test_text, batch_mode=True)
	response, diff = result.corrected_text, result.diff

	assert response is not None
	assert isinstance(response, str)

	cost = workflow.executor.get_total_cost()
	assert cost > 0, "Cost should be positive when usage is returned"

	print_test_results(model_name, test_text, response, diff, workflow.executor)
