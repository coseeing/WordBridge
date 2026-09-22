from dataclasses import dataclass
import json
from pathlib import Path


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
