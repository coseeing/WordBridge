from sqlalchemy import create_engine, inspect
from app.baseModel import Base
from app.user.models import User


def test_user_has_sso_fields_and_no_password():
	engine = create_engine("sqlite+pysqlite:///:memory:")
	Base.metadata.create_all(engine)
	columns = {column["name"]: column for column in inspect(engine).get_columns("user")}
	assert "sso_sub" in columns
	assert "email_verified" in columns
	assert "password" not in columns
	assert User.__table__.c.account.type.length == 254
