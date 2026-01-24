import pytest
from lib.typo_corrector import ChineseTypoCorrector
import json

@pytest.mark.integration
@pytest.mark.slow
def test_gemini_basic_correction(gemini_credentials, gemini_config):
	corrector = ChineseTypoCorrector(
		model=gemini_config["model_name"],
		provider=gemini_config["provider"],
		credential=gemini_credentials,
		language=gemini_config["language"],
		template_name=gemini_config["template_name"],
		optional_guidance_enable=gemini_config["optional_guidance_enable"],
		customized_words=[]
	)

	test_text = "這是測試文字"
	response, diff = corrector.correct_text(test_text, batch_mode=True)

	assert response is not None, "Response should not be None"
	assert isinstance(response, str), "Response should be a string"
	assert isinstance(diff, list), "Diff should be a list"

	cost = corrector.get_total_cost()
	assert cost >= 0, "Cost should be non-negative"

	assert len(corrector.response_history) > 0, "Should have response history"

	print(f"\n=== Test Results ===")
	print(f"Input:  {test_text}")
	print(f"Output: {response}")
	print(f"Cost:   ${cost} USD")
	print(f"API calls: {len(corrector.response_history)}")
	print(f"Diff:   {diff}")

	print("\n=== API Response ===")
	print(json.dumps(corrector.response_history[0], indent=2, ensure_ascii=False))

@pytest.mark.integration
@pytest.mark.slow
def test_gemini_with_typo(gemini_credentials, gemini_config):
	corrector = ChineseTypoCorrector(
		model=gemini_config["model_name"],
		provider=gemini_config["provider"],
		credential=gemini_credentials,
		language=gemini_config["language"],
		template_name=gemini_config["template_name"],
		optional_guidance_enable=gemini_config["optional_guidance_enable"],
		customized_words=[]
	)

	test_text = "今天天器真好"
	response, diff = corrector.correct_text(test_text, batch_mode=True)

	assert response is not None
	assert isinstance(response, str)

	cost = corrector.get_total_cost()

	assert cost >= 0

	print(f"\n=== Typo Correction Test ===")
	print(f"Input:  {test_text}")
	print(f"Output: {response}")
	print(f"Cost:   ${cost} USD")
	print(f"Changed: {test_text != response}")
	print(f"Diff:   {diff}")

	print("\n=== API Response ===")
	print(json.dumps(corrector.response_history[0], indent=2, ensure_ascii=False))
