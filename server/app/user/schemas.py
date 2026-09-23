from pydantic import BaseModel


class User(BaseModel):
	account: str
	name: str
	is_active: bool = False
	is_superuser: bool = False
	quota: float = 0


class Token(BaseModel):
	access_token: str
	token_type: str


class TokenData(BaseModel):
	username: str | None = None
