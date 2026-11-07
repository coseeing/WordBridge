# What kind of failure an LLMServiceError reports. The add-on shows str()
# either way; the Coseeing server turns the kind into its error code.
KINDS = frozenset({"overloaded", "rate_limited", "unreachable", "configuration", "other"})


class LLMServiceError(Exception):
	"""A request to an AI service provider failed, or its answer was unusable.

	str() is the translated message shown to the user, as it was when these
	were raised as plain Exception; callers that catch Exception still do.
	`kind` is one of KINDS: overloaded (HTTP 503, Anthropic's 529),
	rate_limited (429), unreachable (no response), configuration (401, 403,
	404) or other.
	"""

	def __init__(self, message: str = "", *, kind: str = "other"):
		if kind not in KINDS:
			raise ValueError(f"unknown LLMServiceError kind: {kind}")
		super().__init__(message)
		self.kind = kind
