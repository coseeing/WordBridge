from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class TypoCorrectionResult:
	corrected_text: str
	diff: list
	usage_summary: dict
	cost: Decimal
	raw_data: dict = field(default_factory=dict)
