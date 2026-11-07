"""/proofreader holds no database connection while the AI service answers.

The AI call takes seconds to tens of seconds; a connection held for that
long starves every other request of the pool. These tests use a pooled
file database and the real get_optional_user, so the request shares one
session the way it does in production.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main as main_module
from app.baseModel import Base
from app.dependencies import get_db
from app.models.models import Interaction
from app.user.auth import get_verified_sub
from app.user.models import User

PAYLOAD = {
	"request": "以經完成",
	"corrector_config_id": "default",
	"language": "zh_traditional",
	"typo_correction_mode": "standard",
	"customized_words": [],
}


@pytest.fixture
def pooled(tmp_path, monkeypatch):
	engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'pool.db'}")
	Base.metadata.create_all(engine)
	# Like production: default expire_on_commit=True.
	session_factory = sessionmaker(bind=engine)

	def _get_db():
		session = session_factory()
		try:
			yield session
		finally:
			session.close()

	checked_out = []

	def _fake(**kwargs):
		checked_out.append(engine.pool.checkedout())
		return SimpleNamespace(corrected_text="已校正", cost=Decimal("0.000001"))

	monkeypatch.setattr(main_module, "run_typo_correction", _fake)
	main_module.app.dependency_overrides[get_db] = _get_db
	yield SimpleNamespace(engine=engine, session_factory=session_factory, checked_out=checked_out)
	main_module.app.dependency_overrides.clear()
	engine.dispose()


def test_a_guest_request_holds_no_connection_during_the_ai_call(pooled):
	main_module.app.dependency_overrides[get_verified_sub] = lambda: None

	response = TestClient(main_module.app).post("/proofreader", json=PAYLOAD)

	assert response.status_code == 200
	assert pooled.checked_out == [0]


def test_a_signed_in_request_holds_no_connection_and_links_the_user(pooled):
	with pooled.session_factory() as session:
		user = User(
			account="pool@example.org",
			name="Pool",
			sso_sub="sub-pool",
			email_verified=True,
			is_active=True,
			is_superuser=False,
			quota=1000,
		)
		session.add(user)
		session.commit()
		user_id = user.id
	main_module.app.dependency_overrides[get_verified_sub] = lambda: "sub-pool"

	response = TestClient(main_module.app).post(
		"/proofreader",
		json=PAYLOAD,
		headers={"Authorization": "Bearer token"},
	)

	assert response.status_code == 200
	assert pooled.checked_out == [0]
	with pooled.session_factory() as session:
		stored = session.get(Interaction, response.json()["interaction_id"])
		assert stored.user_id == user_id
