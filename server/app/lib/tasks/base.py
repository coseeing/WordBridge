from abc import ABC, abstractmethod


class BasePromptStrategy(ABC):
	@abstractmethod
	def compose(self, input_text: str, response_text_history: list, text_policy):
		raise NotImplementedError


class BaseTextPolicy(ABC):
	@abstractmethod
	def preprocess_input(self, input_text: str) -> str:
		raise NotImplementedError

	@abstractmethod
	def postprocess_output(self, text: str, input_text: str) -> str:
		raise NotImplementedError

	@abstractmethod
	def has_target_language(self, text: str) -> bool:
		raise NotImplementedError

	@abstractmethod
	def normalize_response(self, sentence: str) -> str:
		raise NotImplementedError


class BaseTaskWorkflow(ABC):
	@abstractmethod
	def run(self, input_text: str, batch_mode: bool = True):
		raise NotImplementedError
