from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class Interaction(BaseModel):
	# id: Optional[int]
	request_time: datetime
	response_time: datetime
	request_content: str
	response_content: str
	ip_address: Optional[str]
	cost: float
	model: str
	version: str
	category: Optional[str]
	user_id: int
	machine_id: Optional[int]
	review_content: Optional[str]
	review_user_id: Optional[int]

	class Config:
		from_attributes = True
