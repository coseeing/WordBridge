import json

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.correction_config import SETTING_DIR


CATALOG_PATH = SETTING_DIR / "catalog.json"


def test_root_serves_the_catalog_file_verbatim():
	client = TestClient(main_module.app)

	response = client.get("/")

	assert response.status_code == 200
	assert response.headers["content-type"].startswith("application/json")
	assert response.headers["cache-control"] == "no-cache"
	assert response.content == CATALOG_PATH.read_bytes()


def test_the_served_payload_is_a_schema_1_object_with_local_data():
	body = json.loads(TestClient(main_module.app).get("/").content)

	assert body["schema_version"] == 1
	assert isinstance(body["providers"], dict)
	assert isinstance(body["models"], list)


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


def test_load_catalog_bytes_returns_the_file_bytes_unchanged(tmp_path):
	path = tmp_path / "catalog.json"
	content = b'{\n\t"schema_version": 1, "providers": {}, "models": []\n}\n'
	path.write_bytes(content)

	assert main_module.load_catalog_bytes(path) == content
