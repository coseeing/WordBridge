from dataclasses import dataclass
from typing import Any


@dataclass
class LLMExecutionResult:
	original_text: str
	output_text: str
	raw_response: dict[str, Any]
	usage: dict[str, Any]
