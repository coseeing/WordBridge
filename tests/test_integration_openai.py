import pytest
from lib.typo_corrector import ChineseTypoCorrector
from test_helpers import print_test_results

# Test representative models from different series
OPENAI_MODELS_TO_TEST = [
	"gpt-4.1-2025-04-14",
	"gpt-4o-mini-2024-07-18",
	"o4-mini-2025-04-16",
	"gpt-5"
]

@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("model_name", OPENAI_MODELS_TO_TEST)
def test_openai_basic_correction(model_config, credentials, test_data, model_name):
	config = model_config(model_name, "OpenAI")
	creds = credentials("OpenAI")

	corrector = ChineseTypoCorrector(
		model=config["model_name"],
		provider=config["provider"],
		credential=creds,
		language=config["language"],
		template_name=config["template_name"],
		optional_guidance_enable=config["optional_guidance_enable"],
		customized_words=[]
	)

	test_text = test_data["basic_text"]
	response, diff = corrector.correct_text(test_text, batch_mode=True)

	assert response is not None, "Response should not be None"
	assert isinstance(response, str), "Response should be a string"
	assert isinstance(diff, list), "Diff should be a list"

	cost = corrector.get_total_cost()
	assert cost >= 0, "Cost should be non-negative"

	assert len(corrector.response_history) > 0, "Should have response history"

	print_test_results(model_name, test_text, response, diff, corrector)

@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("model_name", OPENAI_MODELS_TO_TEST)
def test_openai_with_typo(model_config, credentials, test_data, model_name):
	config = model_config(model_name, "OpenAI")
	creds = credentials("OpenAI")

	corrector = ChineseTypoCorrector(
		model=config["model_name"],
		provider=config["provider"],
		credential=creds,
		language=config["language"],
		template_name=config["template_name"],
		optional_guidance_enable=config["optional_guidance_enable"],
		customized_words=[]
	)

	test_text = test_data["text_with_typo"]
	response, diff = corrector.correct_text(test_text, batch_mode=True)

	assert response is not None
	assert isinstance(response, str)

	cost = corrector.get_total_cost()

	assert cost >= 0

	print_test_results(model_name, test_text, response, diff, corrector)
