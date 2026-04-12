import json
import pytest

from lib.application.task_factory import create_typo_workflow


def run_workflow_or_skip_transient_failure(workflow, test_text, batch_mode=True):
	try:
		return workflow.run(test_text, batch_mode=batch_mode)
	except Exception as exc:
		message = str(exc)
		transient_markers = [
			"Rate limit reached",
			"The server is currently overloaded",
			"quota",
		]
		if any(marker in message for marker in transient_markers):
			pytest.skip(f"Transient provider failure: {message}")
		raise

def print_test_results(model_name, test_text, response, diff, corrector):
	cost = corrector.get_total_cost()

	print(f"\n=== Test Results ({model_name}) ===")
	print(f"Input:  {test_text}")
	print(f"Output: {response}")
	print(f"Cost:   ${cost} USD")
	print(f"API calls: {len(corrector.response_history)}")
	print(f"Diff:   {diff}")

	print("\n=== API Response ===")
	print(json.dumps(corrector.response_history[0], indent=2, ensure_ascii=False))


def build_typo_workflow_for_provider(
	provider_name,
	model_name,
	model_config,
	credentials,
	language="zh_traditional",
	template_name="Standard_v1.json",
	corrector_mode="standard",
	optional_guidance_enable=None,
	customized_words=None,
):
	config = model_config(model_name, provider_name)
	creds = credentials(provider_name)
	return create_typo_workflow(
		provider_name=provider_name,
		model_name=config["name"],
		credential=creds,
		language=language or config["language"],
		template_name=template_name or config["template_name"],
		corrector_mode=corrector_mode,
		optional_guidance_enable=optional_guidance_enable or config["optional_guidance_enable"],
		customized_words=customized_words or [],
	)
