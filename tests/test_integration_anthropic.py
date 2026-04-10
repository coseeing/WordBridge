import pytest
from lib.application.task_factory import create_typo_workflow
from test_helpers import print_test_results, run_workflow_or_skip_transient_failure

# Test representative Anthropic Claude models
ANTHROPIC_MODELS_TO_TEST = [
	"claude-sonnet-4-20250514",
	"claude-haiku-4-5-20251001",
]

@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("model_name", ANTHROPIC_MODELS_TO_TEST)
def test_anthropic_basic_correction(model_config, credentials, test_data, model_name):
	config = model_config(model_name, "Anthropic")
	creds = credentials("Anthropic")
	workflow = create_typo_workflow(
		provider_name="Anthropic",
		model_name=config["name"],
		credential=creds,
		language=config["language"],
		template_name=config["template_name"],
		corrector_mode="standard",
		optional_guidance_enable=config["optional_guidance_enable"],
		customized_words=[],
	)

	test_text = test_data["basic_text"]
	result = run_workflow_or_skip_transient_failure(workflow, test_text, batch_mode=True)
	response, diff = result.corrected_text, result.diff

	assert response is not None, "Response should not be None"
	assert isinstance(response, str), "Response should be a string"
	assert isinstance(diff, list), "Diff should be a list"

	cost = workflow.executor.get_total_cost()
	assert cost >= 0, "Cost should be non-negative"

	assert len(workflow.executor.response_history) > 0, "Should have response history"

	print_test_results(model_name, test_text, response, diff, workflow.executor)

@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("model_name", ANTHROPIC_MODELS_TO_TEST)
def test_anthropic_with_typo(model_config, credentials, test_data, model_name):
	config = model_config(model_name, "Anthropic")
	creds = credentials("Anthropic")
	workflow = create_typo_workflow(
		provider_name="Anthropic",
		model_name=config["name"],
		credential=creds,
		language=config["language"],
		template_name=config["template_name"],
		corrector_mode="standard",
		optional_guidance_enable=config["optional_guidance_enable"],
		customized_words=[],
	)

	test_text = test_data["text_with_typo"]
	result = run_workflow_or_skip_transient_failure(workflow, test_text, batch_mode=True)
	response, diff = result.corrected_text, result.diff

	assert response is not None
	assert isinstance(response, str)

	cost = workflow.executor.get_total_cost()
	assert cost >= 0

	print_test_results(model_name, test_text, response, diff, workflow.executor)
