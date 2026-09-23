"""
Cost Calculator for tracking LLM usage and costs.

This module provides utilities for:
- Tracking token usage from API responses
- Calculating costs based on model pricing
"""

from collections import defaultdict
from decimal import Decimal


class CostCalculator:
	def __init__(self, model_entry: dict):
		self._model_entry = model_entry
		self._pricing = model_entry.get("pricing", {})
		self._usage_key = model_entry.get("usage_key")

	def get_total_usage(self, response_history: list) -> dict:
		total_usage = defaultdict(int)

		for response in response_history:
			if not isinstance(response, dict):
				continue

			if self._usage_key and self._usage_key in response:
				usage_source = response[self._usage_key]
			else:
				usage_source = response

			for usage_type in self._pricing:
				if usage_type == "base_unit":
					continue
				try:
					total_usage[usage_type] += usage_source[usage_type]
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
