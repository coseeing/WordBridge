"""
Cost Calculator for tracking LLM usage and costs.

This module provides utilities for:
- Tracking token usage from API responses
- Calculating costs based on model pricing
"""

from decimal import Decimal
from collections import defaultdict

class CostCalculator:
	def __init__(self, model_entry: dict):
		self._model_entry = model_entry
		self._pricing = model_entry.get("pricing", {})
		self._usage_key = model_entry.get("usage_key")

	def get_total_usage(self, response_history: list) -> dict:
		total_usage = defaultdict(int)
		if not self._usage_key:
			return total_usage

		for response in response_history:
			if isinstance(response, dict) and self._usage_key in response:
				for usage_type in self._pricing:
					if usage_type == "base_unit":
						continue
					try:
						total_usage[usage_type] += response[self._usage_key][usage_type]
					except KeyError:
						pass

		return dict(total_usage)

	def get_total_cost(self, response_history: list) -> Decimal:
		cost = Decimal("0")
		usages = self.get_total_usage(response_history)
		for key, value in usages.items():
			cost += (
				Decimal(str(self._pricing[key]))
				* Decimal(str(value))
				/ Decimal(str(self._pricing["base_unit"]))
			)
		return cost
