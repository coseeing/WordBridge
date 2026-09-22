from dataclasses import dataclass
import json
from pathlib import Path

try:
	import addonHandler
	addonHandler.initTranslation()
except ImportError:
	pass

# Under NVDA _ is a builtin and never a global, so `if "_" not in globals()`
# was always true and shadowed the translation function. A bare _ lookup here
# resolves through globals and then builtins, so the fallback is only defined
# when neither has one.
try:
	_
except NameError:
	def _(s):
		return s


@dataclass(frozen=True)
class CorrectorTaskConfig:
	template_name: dict
	optional_guidance_enable: dict


def load_corrector_task_config(path) -> CorrectorTaskConfig:
	with Path(path).open("r", encoding="utf8") as f:
		raw_config = json.load(f)

	return CorrectorTaskConfig(
		template_name=raw_config["template_name"],
		optional_guidance_enable=raw_config["optional_guidance_enable"],
	)
