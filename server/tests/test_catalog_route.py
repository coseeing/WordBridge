import json

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.correction_config import SETTING_DIR

CATALOG_PATH = SETTING_DIR / "catalog.json"


def test_root_serves_the_catalog_without_providers():
	# The add-on bundles its provider entries; the file keeps them for the
	# server's own correction calls, but they are never served (B2).
	client = TestClient(main_module.app)
	document = json.loads(CATALOG_PATH.read_bytes())

	response = client.get("/")

	assert response.status_code == 200
	assert response.headers["content-type"].startswith("application/json")
	assert response.headers["cache-control"] == "no-cache"
	body = json.loads(response.content)
	assert "providers" in document
	assert "providers" not in body
	assert body["models"] == document["models"]
	assert set(body) == set(document) - {"providers"}


def test_the_served_payload_is_a_schema_1_object_with_local_data():
	body = json.loads(TestClient(main_module.app).get("/").content)

	assert body["schema_version"] == 1
	assert "providers" not in body
	assert isinstance(body["models"], list)
	# The Coseeing channel ships in the add-on; the servable Coseeing ids are
	# the server's own list (COSEEING_MODEL_IDS), never part of the payload.
	assert "coseeings" not in body


def test_root_needs_no_authentication_and_sets_no_cookie():
	response = TestClient(main_module.app).get("/", headers={})

	assert response.status_code == 200
	assert "set-cookie" not in response.headers


@pytest.mark.parametrize("content", [b"[]", b'{"schema_version": 2}', b"{not json", b'{"providers": {}}'],
	ids=["array", "schema-2", "not-json", "schema-missing"])
def test_load_catalog_bytes_rejects_a_bad_file(tmp_path, content):
	path = tmp_path / "catalog.json"
	path.write_bytes(content)

	with pytest.raises(ValueError):
		main_module.load_catalog_bytes(path)


def test_load_catalog_bytes_keeps_every_other_key_in_file_order(tmp_path):
	path = tmp_path / "catalog.json"
	models = [{"provider": "OpenAI", "model": "m", "label": "模型"}]
	path.write_text(json.dumps({
		"schema_version": 1,
		"providers": {"OpenAI": {"url": "https://api.openai.com/v1/responses"}},
		"models": models,
		"extra": {"x": 1},
	}, ensure_ascii=False), encoding="utf8")

	content = main_module.load_catalog_bytes(path)

	served = json.loads(content)
	assert list(served) == ["schema_version", "models", "extra"]
	assert served == {"schema_version": 1, "models": models, "extra": {"x": 1}}
	# UTF-8 text, as in the file, not \u escapes.
	assert "模型".encode() in content


def test_load_catalog_bytes_accepts_a_file_without_providers(tmp_path):
	path = tmp_path / "catalog.json"
	path.write_text('{"schema_version": 1, "models": []}', encoding="utf8")

	assert json.loads(main_module.load_catalog_bytes(path)) == {"schema_version": 1, "models": []}
