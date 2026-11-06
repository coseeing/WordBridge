class LLMServiceError(Exception):
	"""A request to an AI service provider failed, or its answer was unusable.

	str() is the translated message shown to the user, as it was when these
	were raised as plain Exception; callers that catch Exception still do.
	"""
