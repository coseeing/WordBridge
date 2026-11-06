from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..baseModel import Base

if TYPE_CHECKING:
	# Only for the annotation: app.user.models imports this module.
	from ..user.models import User


class Interaction(Base):
	__tablename__ = "interaction"
	id: Mapped[int] = mapped_column(primary_key=True, init=False)
	request_time: Mapped[datetime] = mapped_column(DateTime)
	response_time: Mapped[datetime] = mapped_column(DateTime)
	request_content: Mapped[str] = mapped_column(Text)
	response_content: Mapped[str] = mapped_column(Text)
	ip_address: Mapped[str] = mapped_column(String(45), nullable=True)
	cost: Mapped[Decimal] = mapped_column(Numeric(15, 12))
	model: Mapped[str] = mapped_column(String(64))
	version: Mapped[str] = mapped_column(String(8))
	category: Mapped[str] = mapped_column(String(8), nullable=True, init=False)
	user_id = mapped_column(ForeignKey("user.id"))
	user: Mapped["User"] = relationship("User", back_populates="interactions", foreign_keys=[user_id])
	machine_id: Mapped[int] = mapped_column(nullable=True, init=False)
	review_content: Mapped[str] = mapped_column(Text, nullable=True, init=False)
	review_user_id = mapped_column(ForeignKey("user.id"))
