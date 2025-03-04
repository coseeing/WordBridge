from collections import defaultdict
from dataclasses import dataclass
import glob
import json
import os


LABEL_DICT = {
	"Baidu": _("Baidu"),
	"Coseeing": _("Coseeing"),
	"DeepSeek": _("DeepSeek"),
	"OpenAI": _("OpenAI"),
	"OpenRouter": _("OpenRouter"),
	"gpt-3.5-turbo": _("gpt-3.5-turbo"),
	"gpt-4-turbo": _("gpt-4-turbo"),
	"gpt-4o": _("gpt-4o"),
	"gpt-4o-mini": _("gpt-4o-mini"),
	"ernie-4.0-turbo-8k": _("ernie-4.0-turbo-8k"),
	"deepseek-v3": _("deepseek-v3"),
	"deepseek-chat": _("deepseek-chat"),
	"deepseek/deepseek-chat:free": _("deepseek/deepseek-chat:free"),
	"deepseek/deepseek-r1:free": _("deepseek/deepseek-r1:free"),
	"o1-mini": _("o1-mini"),
	"o1-preview": _("o1-preview"),
	"o3-mini": _("o3-mini"),
	"ernie-4.0-8k-preview": _("ernie-4.0-8k-preview"),
}


class ConfigManager:
	def __init__(self, path):
		self.configs = []
		self.endpoint = defaultdict(list)
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

			label= f"{endpoint_text}: {model_name_text}"
			value = corrector_config
			filename = os.path.basename(item)

			config = Config(label=label, value=value, filename=filename)
			self.configs.append(config)
			self.endpoint[provider].append(config)

	@property
	def labels(self):
		return [item.label for item in self.endpoint[self.provider]] if self.provider else [item.label for item in self.configs]

	@property
	def filenames(self):
		return [item.filename for item in self.endpoint[self.provider]] if self.provider else [item.filename for item in self.configs]

	@property
	def values(self):
		return [item.value for item in self.endpoint[self.provider]] if self.provider else [item.value for item in self.configs]

@dataclass
class Config:
	filename: str
	label: str
	value: dict
