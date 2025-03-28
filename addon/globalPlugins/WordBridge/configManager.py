from collections import defaultdict
from dataclasses import dataclass
import glob
import json
import os

LABEL_DICT = {

	"Anthropic": _("Anthropic"),
	"Baidu": _("Baidu"),
	"Coseeing": _("Coseeing"),
	"DeepSeek": _("DeepSeek"),
	"OpenAI": _("OpenAI"),
	"OpenRouter": _("OpenRouter"),
	"claude-3-5-haiku-latest": _("claude-3-5-haiku"),
	"claude-3-5-sonnet-latest": _("claude-3-5-sonnet"),
	"claude-3-7-sonnet-latest": _("claude-3-7-sonnet"),
	"deepseek-v3": _("deepseek-v3"),
	"deepseek-chat": _("deepseek-chat"),
	"deepseek/deepseek-chat:free": _("deepseek-chat(free)"),
	"deepseek/deepseek-chat-v3-0324:free": _("deepseek-chat-0324(free)"),
	"deepseek/deepseek-r1:free": _("deepseek-reasoner(free)"),
	"gpt-3.5-turbo": _("gpt-3.5-turbo"),
	"gpt-4-turbo": _("gpt-4-turbo"),
	"gpt-4o": _("gpt-4o"),
	"gpt-4o-mini": _("gpt-4o-mini"),
	"o1-mini": _("o1-mini"),
	"o1": _("o1"),
	"o3-mini": _("o3-mini"),
	"ernie-4.0-turbo-8k": _("ernie-4.0-turbo-8k"),
	"ernie-4.0-8k-preview": _("ernie-4.0-8k-preview"),
}


class ConfigManager:
	def __init__(self, path):
		self.configs = []
		self.endpoints = defaultdict(list)
		self.provider = ""

		for item in sorted(glob.glob(os.path.join(path, "*.json"))):
			with open(item, "r", encoding="utf8") as f:
				corrector_config = json.loads(f.read())

			if corrector_config['model']['llm_access_method'] != "coseeing_relay":
				provider = corrector_config['model']['provider']
			else:
				provider = "Coseeing"

			endpoint_text = LABEL_DICT[provider]
			model_name_text = LABEL_DICT[corrector_config['model']['model_name']]

			label= model_name_text
			value = corrector_config
			filename = os.path.basename(item)

			config = Config(label=label, value=value, filename=filename)
			self.configs.append(config)
			self.endpoints[provider].append(config)

	@property
	def model_labels(self):
		return [item.label for item in self.endpoints[self.provider]] if self.provider else [item.label for item in self.configs]

	@property
	def endpoint_labels(self):
		return [LABEL_DICT[item] for item in self.endpoints]

	def find_index_by_filename(self, value):
		provider_mapping = {key: idx for idx, key in enumerate(self.endpoints.keys())}
    
		for provider_key, config_list in self.endpoints.items():
			filename_list = [config.filename for config in config_list]
			if value in filename_list:
				provider_index = provider_mapping[provider_key]
				config_index = filename_list.index(value)
				return (provider_index, config_index)
    
		return (-1, -1)

	def get_config_by_index(self, endpoint_index, model_index):
		endpoint_key = list(self.endpoints.keys())[endpoint_index]
		return self.endpoints[endpoint_key][model_index]

	def get_config_by_filename(self, value):
		endpoint_index, model_index = self.find_index_by_filename(value)
		endpoint_key = list(self.endpoints.keys())[endpoint_index]
		return self.endpoints[endpoint_key][model_index]


@dataclass
class Config:
	filename: str
	label: str
	value: dict
