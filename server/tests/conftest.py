import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# app.settings reads every deployment setting at import and refuses to start
# without them. Pin them for the whole run, ahead of any app import, so the
# suite never depends on the shell or on server/.env. The database values
# are never used: the tests swap in sqlite sessions.
os.environ.update(
	{
		"DEFAULT_CORRECTOR_CONFIG_ID": "deepseek-flash&DeepSeek",
		"COSEEING_MODEL_IDS": "deepseek-flash&DeepSeek,gpt-6-luna&OpenAI",
		"SSO_ISSUER": "https://sso.coseeing.org",
		"SSO_CLIENT_ID": "wordbridge",
		"SSO_USERINFO_URL": "https://sso.coseeing.org/userinfo",
		"SSO_USERINFO_TIMEOUT_SECONDS": "6",
		"DB_USER": "wordbridge",
		"DB_PASS": "test-only",
		"DB_HOST": "localhost",
		"DB_PORT": "3306",
		"DATABASE": "WordBridge",
		"GUEST_TEXT_LIMIT": "128",
		"GUEST_IP_QUOTA": "0.06",
		"GUEST_GLOBAL_QUOTA": "0.3",
		"QUOTA_WINDOW_HOURS": "24",
	},
)

from app.baseModel import Base

# Imported for its side effect: it maps the user table onto Base.metadata,
# which the fixtures below create.
from app.user.models import User  # noqa: F401


@pytest.fixture
def db():
	engine = create_engine(
		"sqlite+pysqlite://",
		connect_args={"check_same_thread": False},
		poolclass=StaticPool,
	)
	Base.metadata.create_all(engine)
	with Session(engine) as session:
		yield session
	Base.metadata.drop_all(engine)
	engine.dispose()
