from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass
class LLMExecutionResult:
	original_text: str
	output_text: str
	request_payload: dict[str, Any] = field(default_factory=dict)
	raw_response: dict[str, Any] = field(default_factory=dict)
	usage: dict[str, Any] = field(default_factory=dict)
	raw_usage: dict[str, Any] = field(default_factory=dict)
	latency_ms: float = 0.0
	request_cost: Decimal = Decimal("0")
