from datetime import datetime

from pydantic import BaseModel


class Interaction(BaseModel):
	# id: Optional[int]
	request_time: datetime
	response_time: datetime
	request_content: str
	response_content: str
	ip_address: str | None
	cost: float
	model: str
	version: str
	template: str
	user_id: int
	machine_id: int | None
	review_content: str | None
	review_user_id: int | None

	class Config:
		from_attributes = True
