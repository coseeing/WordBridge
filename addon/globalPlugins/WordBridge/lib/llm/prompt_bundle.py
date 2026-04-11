from dataclasses import dataclass


@dataclass
class PromptBundle:
	messages: list[dict[str, str]]
	system_template: str
