from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..baseModel import Base

if TYPE_CHECKING:
	# Only for the annotation: app.user.models imports this module.
	from ..user.models import User


class Interaction(Base):
	__tablename__ = "interaction"
	# The quota queries (app/main.py _sum_cost): a signed-in user's or all
	# guests' spending (user_id, request_time), and one guest IP's
	# (ip_address, request_time).
	__table_args__ = (
		Index("ix_interaction_user_id_request_time", "user_id", "request_time"),
		Index("ix_interaction_ip_address_request_time", "ip_address", "request_time"),
	)
	id: Mapped[int] = mapped_column(primary_key=True, init=False)
	request_time: Mapped[datetime] = mapped_column(DateTime)
	response_time: Mapped[datetime] = mapped_column(DateTime)
	request_content: Mapped[str] = mapped_column(Text)
	response_content: Mapped[str] = mapped_column(Text)
	ip_address: Mapped[str] = mapped_column(String(45), nullable=True)
	cost: Mapped[Decimal] = mapped_column(Numeric(15, 12))
	model: Mapped[str] = mapped_column(String(64))
	# The add-on version the server's code and prompts correspond to
	# (app/setting/addon_version.txt, from buildVars.py).
	version: Mapped[str] = mapped_column(String(32))
	# The prompt template used, without .json, e.g. Standard_v1.
	template: Mapped[str] = mapped_column(String(64))
	user_id = mapped_column(ForeignKey("user.id"))
	user: Mapped["User"] = relationship("User", back_populates="interactions", foreign_keys=[user_id])
	machine_id: Mapped[int] = mapped_column(nullable=True, init=False)
	review_content: Mapped[str] = mapped_column(Text, nullable=True, init=False)
	review_user_id = mapped_column(ForeignKey("user.id"))
