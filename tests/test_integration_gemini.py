import pytest
from lib.instruction_composer import StandardInstructionComposer
from lib.language_text_policy import StandardChineseTextPolicy
from lib.provider import get_provider
from lib.provider_model_adapter import get_provider_model_adapter
from lib.typo_corrector import ChineseTypoCorrector, CorrectionOrchestrator
from test_helpers import print_test_results

# Test representative Gemini models
GEMINI_MODELS_TO_TEST = [
	"gemini-2.5-flash",
	"gemini-2.5-pro",
]

@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("model_name", GEMINI_MODELS_TO_TEST)
def test_gemini_basic_correction(model_config, credentials, test_data, model_name):
	config = model_config(model_name, "Google")
	creds = credentials("Google")
	provider_object = get_provider("Google", creds)
	adapter_object = get_provider_model_adapter("Google", config["name"])
	instruction_composer = StandardInstructionComposer(
		language=config["language"],
		template_name=config["template_name"],
		optional_guidance_enable=config["optional_guidance_enable"],
		customized_words=[],
	)
	language_text_policy = StandardChineseTextPolicy(config["language"])

	corrector = ChineseTypoCorrector(
		provider_object=provider_object,
		adapter_object=adapter_object,
		instruction_composer=instruction_composer,
		language_text_policy=language_text_policy,
	)

	orchestrator = CorrectionOrchestrator(corrector)
	test_text = test_data["basic_text"]
	response, diff = orchestrator.execute(test_text, batch_mode=True)

	assert response is not None, "Response should not be None"
	assert isinstance(response, str), "Response should be a string"
	assert isinstance(diff, list), "Diff should be a list"

	cost = corrector.get_total_cost()
	assert cost >= 0, "Cost should be non-negative"

	assert len(corrector.response_history) > 0, "Should have response history"

	print_test_results(model_name, test_text, response, diff, corrector)

@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("model_name", GEMINI_MODELS_TO_TEST)
def test_gemini_with_typo(model_config, credentials, test_data, model_name):
	config = model_config(model_name, "Google")
	creds = credentials("Google")
	provider_object = get_provider("Google", creds)
	adapter_object = get_provider_model_adapter("Google", config["name"])
	instruction_composer = StandardInstructionComposer(
		language=config["language"],
		template_name=config["template_name"],
		optional_guidance_enable=config["optional_guidance_enable"],
		customized_words=[],
	)
	language_text_policy = StandardChineseTextPolicy(config["language"])

	corrector = ChineseTypoCorrector(
		provider_object=provider_object,
		adapter_object=adapter_object,
		instruction_composer=instruction_composer,
		language_text_policy=language_text_policy,
	)

	orchestrator = CorrectionOrchestrator(corrector)
	test_text = test_data["text_with_typo"]
	response, diff = orchestrator.execute(test_text, batch_mode=True)

	assert response is not None
	assert isinstance(response, str)

	cost = corrector.get_total_cost()
	assert cost >= 0

	print_test_results(model_name, test_text, response, diff, corrector)
