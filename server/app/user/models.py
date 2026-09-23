from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Boolean, Column, Double, Integer, String, DateTime, Text, ForeignKey

from ..baseModel import Base
from ..models.models import Interaction


class User(Base):
	__tablename__ = "user"
	id: Mapped[int] = mapped_column(init=False, primary_key=True)
	account: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
	name: Mapped[str] = mapped_column(String(30))
	sso_sub: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True, default=None)
	email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
	is_active: Mapped[bool] = mapped_column(Boolean, default=False)
	is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
	quota: Mapped[float] = mapped_column(Double, default=0)
	interactions: Mapped[List["Interaction"]] = relationship("Interaction", back_populates="user", foreign_keys="[Interaction.user_id]", init=False, repr=False)
