def build_coseeing_headers(access_token: str | None) -> dict[str, str]:
	if access_token is None:
		return {}
	if not access_token:
		raise ValueError("access token must not be empty")
	return {"Authorization": f"Bearer {access_token}"}
