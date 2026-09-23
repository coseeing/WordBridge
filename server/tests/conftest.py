import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.baseModel import Base
from app.user.models import User


@pytest.fixture
def db():
	engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
	Base.metadata.create_all(engine)
	with Session(engine) as session:
		yield session
	Base.metadata.drop_all(engine)
	engine.dispose()
