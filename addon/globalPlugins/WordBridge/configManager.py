from dataclasses import dataclass
import json
from pathlib import Path

try:
	import addonHandler
	addonHandler.initTranslation()
except ImportError:
	def _(s):
		return s

if "_" not in globals():
	def _(s):
		return s


LABEL_DICT = {
	"Anthropic": _("Anthropic"),
	"Baidu": _("Baidu"),
	"Coseeing": _("Coseeing"),
	"DeepSeek": _("DeepSeek"),
	"Google": _("Google"),
	"OpenAI": _("OpenAI"),
	"OpenAIChatCompletion": _("OpenAI Chat Completion"),
	"OpenAIResponse": _("OpenAI Response"),
	"OpenRouter": _("OpenRouter"),
	"claude-haiku-4-5-20251001": _("claude-4-5-haiku"),
	"claude-3-7-sonnet-20250219": _("claude-3.7-sonnet"),
	"claude-sonnet-4-20250514": _("claude-4-sonnet"),
	"deepseek-v3": _("deepseek-v3"),
	"deepseek-chat": _("deepseek-chat"),
	"deepseek-reasoner": _("deepseek-reasoner"),
	"deepseek/deepseek-chat:free": _("deepseek-chat(free)"),
	"deepseek/deepseek-chat-v3-0324:free": _("deepseek-chat-0324(free)"),
	"deepseek/deepseek-r1-0528:free": _("deepseek-chat-0528(free)"),
	"deepseek/deepseek-r1-0528-qwen3-8b:free": _("deepseek-chat-0528-qwen3-8b(free)"),
	"gemini-2.5-flash-preview-05-20": _("gemini-2.5-flash"),
	"gemini-2.5-pro-preview-06-05": _("gemini-2.5-pro"),
	"gpt-4o-2024-08-06": _("gpt-4o"),
	"gpt-4o-mini-2024-07-18": _("gpt-4o-mini"),
	"gpt-4.1-2025-04-14": _("gpt-4.1"),
	"gpt-4.1-mini-2025-04-14": _("gpt-4.1-mini"),
	"gpt-4.1-nano-2025-04-14": _("gpt-4.1-nano"),
	"gpt-5.4-2026-03-05": _("gpt-5.4"),
	"gpt-5.4-mini-2026-03-17": _("gpt-5.4-mini"),
	"gpt-5.4-nano-2026-03-17": _("gpt-5.4-nano"),
	"gpt-5.2-2025-12-11": _("gpt-5.2"),
	"gpt-5.1-2025-11-13": _("gpt-5.1"),
	"gpt-5-2025-08-07": _("gpt-5"),
	"gpt-5-mini-2025-08-07": _("gpt-5-mini"),
	"gpt-5-nano-2025-08-07": _("gpt-5-nano"),
	"gpt-5-chat-latest": _("gpt-5-chat-latest"),
	"gpt-5": _("gpt-5"),
	"gpt-5-mini": _("gpt-5-mini"),
	"gpt-5-nano": _("gpt-5-nano"),
	"o3-2025-04-16": _("o3"),
	"o3-mini-2025-01-31": _("o3-mini"),
	"o4-mini-2025-04-16": _("o4-mini"),
	"ernie-4.0-turbo-8k": _("ernie-4.0-turbo-8k"),
}


def make_corrector_config_id(model: str, provider: str) -> str:
	if "&" in model or "&" in provider:
		raise ValueError("model and provider must not contain '&'")
	return f"{model}&{provider}"


def normalize_selection(config_manager, corrector_config_id: str, execution_channel: str):
	config = config_manager.get_config(corrector_config_id)
	if config is None:
		corrector_config_id, execution_channel = config_manager.default_selection()
		config = config_manager.get_config(corrector_config_id)

	if execution_channel not in {"local", "Coseeing"}:
		execution_channel = "local"

	if execution_channel == "Coseeing" and not config.coseeing:
		execution_channel = "local"

	return corrector_config_id, execution_channel, config


@dataclass(frozen=True)
class CorrectorConfig:
	model: str
	provider: str
	coseeing: bool
	template_name: dict
	optional_guidance_enable: dict

	@property
	def corrector_config_id(self) -> str:
		return make_corrector_config_id(self.model, self.provider)


@dataclass(frozen=True)
class SelectableItem:
	provider_group: str
	corrector_config_id: str
	execution_channel: str
	label: str
	config: CorrectorConfig


class ConfigManager:
	def __init__(self, path):
		self.path = Path(path)
		self.configs = []
		self.config_by_id = {}
		self.endpoints = {}
		self.provider = ""

		self._load_configs()
		self._build_selectable_items()

	def _load_configs(self):
		for item in sorted(self.path.glob("*.json")):
			with item.open("r", encoding="utf8") as f:
				raw_config = json.load(f)

			config = CorrectorConfig(
				model=raw_config["model"],
				provider=raw_config["provider"],
				coseeing=raw_config["coseeing"],
				template_name=raw_config["template_name"],
				optional_guidance_enable=raw_config["optional_guidance_enable"],
			)
			if config.corrector_config_id in self.config_by_id:
				raise ValueError(f"Duplicate corrector config id: {config.corrector_config_id}")

			self.configs.append(config)
			self.config_by_id[config.corrector_config_id] = config

	def _build_selectable_items(self):
		for config in self.configs:
			self._append_selectable_item(
				provider_group=config.provider,
				execution_channel="local",
				config=config,
			)
			if config.coseeing:
				self._append_selectable_item(
					provider_group="Coseeing",
					execution_channel="Coseeing",
					config=config,
				)

	def _append_selectable_item(self, provider_group: str, execution_channel: str, config: CorrectorConfig):
		item = SelectableItem(
			provider_group=provider_group,
			corrector_config_id=config.corrector_config_id,
			execution_channel=execution_channel,
			label=LABEL_DICT.get(config.model, config.model),
			config=config,
		)
		self.endpoints.setdefault(provider_group, []).append(item)

	def get_config(self, corrector_config_id: str) -> CorrectorConfig | None:
		return self.config_by_id.get(corrector_config_id)

	def default_selection(self) -> tuple[str, str]:
		coseeing_items = self.endpoints.get("Coseeing", [])
		if coseeing_items:
			first_item = coseeing_items[0]
			return (first_item.corrector_config_id, first_item.execution_channel)

		default_config_id = sorted(self.config_by_id)[0]
		return (default_config_id, "local")

	@property
	def provider_groups(self):
		provider_groups = sorted(group for group in self.endpoints if group != "Coseeing")
		if "Coseeing" in self.endpoints:
			return ["Coseeing"] + provider_groups
		return provider_groups

	@property
	def model_labels(self):
		return [item.label for item in self.endpoints.get(self.provider, [])] if self.provider else []

	@property
	def endpoint_labels(self):
		return [LABEL_DICT[item] for item in self.provider_groups]

	def find_selection(self, corrector_config_id: str, execution_channel: str) -> tuple[int, int]:
		provider_mapping = {key: idx for idx, key in enumerate(self.provider_groups)}

		for provider_group in self.provider_groups:
			selectable_items = self.endpoints[provider_group]
			for model_index, item in enumerate(selectable_items):
				if (
					item.corrector_config_id == corrector_config_id
					and item.execution_channel == execution_channel
				):
					return (provider_mapping[provider_group], model_index)

		return (-1, -1)

	def get_item_by_index(self, endpoint_index: int, model_index: int) -> SelectableItem:
		provider_group = self.provider_groups[endpoint_index]
		return self.endpoints[provider_group][model_index]
