from ..llm.adapter import get_provider_model_adapter
from ..llm.executor import LLMExecutor
from ..llm.provider import get_provider
from ..tasks.typo.prompt import LiteTypoPromptStrategy, StandardTypoPromptStrategy
from ..tasks.typo.text_policy import LiteTypoTextPolicy, StandardTypoTextPolicy
from ..tasks.typo.workflow import TypoCorrectionWorkflow


def create_typo_workflow(
	*,
	provider_name: str,
	model_name: str,
	credential: dict,
	language: str,
	template_name: str,
	corrector_mode: str,
	optional_guidance_enable: dict,
	customized_words: list | None = None,
	retries: int = 2,
	backoff: int = 1,
	max_correction_attempts: int = 3,
):
	provider_object = get_provider(provider_name, credential, retries=retries, backoff=backoff)
	adapter_object = get_provider_model_adapter(provider_name, model_name)
	executor = LLMExecutor(provider_object, adapter_object)

	customized_words = customized_words or []
	if corrector_mode == "lite":
		prompt_strategy = LiteTypoPromptStrategy(
			language=language,
			template_name=template_name,
			optional_guidance_enable=optional_guidance_enable,
			customized_words=customized_words,
		)
		text_policy = LiteTypoTextPolicy(language)
	else:
		prompt_strategy = StandardTypoPromptStrategy(
			language=language,
			template_name=template_name,
			optional_guidance_enable=optional_guidance_enable,
			customized_words=customized_words,
		)
		text_policy = StandardTypoTextPolicy(language)

	return TypoCorrectionWorkflow(
		executor=executor,
		prompt_strategy=prompt_strategy,
		text_policy=text_policy,
		max_correction_attempts=max_correction_attempts,
	)
