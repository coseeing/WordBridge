from .adapter import (
	ADAPTER_CLASSES,
	AnthropicAdapter,
	DeepSeekAdapter,
	GoogleAdapter,
	OpenAIAdapter,
	OpenRouterAdapter,
	ProviderModelAdapter,
	get_provider_model_adapter,
)
from .errors import LLMServiceError
from .executor import LLMExecutor
from .prompt_bundle import PromptBundle
from .provider import (
	PROVIDER_CLASSES,
	AnthropicProvider,
	DeepseekProvider,
	GoogleProvider,
	OpenAIProvider,
	OpenrouterProvider,
	Provider,
	get_provider,
)
from .result import LLMExecutionResult

# The intersection, not either table alone: a name in one and not the other is
# a model the user could select and could not run.
SUPPORTED_PROVIDERS = frozenset(PROVIDER_CLASSES) & frozenset(ADAPTER_CLASSES)

__all__ = [
	"ADAPTER_CLASSES",
	"PROVIDER_CLASSES",
	"SUPPORTED_PROVIDERS",
	"AnthropicAdapter",
	"AnthropicProvider",
	"DeepSeekAdapter",
	"DeepseekProvider",
	"GoogleAdapter",
	"GoogleProvider",
	"LLMExecutionResult",
	"LLMExecutor",
	"LLMServiceError",
	"OpenAIAdapter",
	"OpenAIProvider",
	"OpenRouterAdapter",
	"OpenrouterProvider",
	"PromptBundle",
	"Provider",
	"ProviderModelAdapter",
	"get_provider",
	"get_provider_model_adapter",
]
