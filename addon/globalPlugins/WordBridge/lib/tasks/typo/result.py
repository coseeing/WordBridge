from dataclasses import dataclass
from decimal import Decimal


@dataclass
class TypoCorrectionResult:
	corrected_text: str
	diff: list
	usage_summary: dict
	cost: Decimal
