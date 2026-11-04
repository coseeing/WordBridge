import json
from pathlib import Path

import pytest

from lib.catalog.overlay import accept_remote_document, has_local_items
from lib.catalog.remote import check_remote_document, parse_remote_payload
from lib.llm import SUPPORTED_PROVIDERS


SERVER_CATALOG = Path(__file__).resolve().parents[1] / "server" / "app" / "setting" / "catalog.json"
SERVER_BYTES = SERVER_CATALOG.read_bytes()


class BundledSentinel:
	def load(self):
		return {"schema_version": 1, "coseeings": [{"model": "default", "label": "default"}]}, ()


def _body(**document):
	return json.dumps(document).encode("utf8")


# (id, body, code) -- code None means the payload parses.
PARSE_TABLE = [
	("valid", SERVER_BYTES, None),
	("utf8-bom", b"\xef\xbb\xbf" + SERVER_BYTES, None),
	("not-json", b"{not json", "remote_malformed"),
	("array", b"[]", "remote_malformed"),
	("schema-2", _body(schema_version=2, providers={}, models=[]), "remote_schema_version"),
	("schema-missing", _body(providers={}, models=[]), "remote_schema_version"),
	# 1.0 == 1 and True == 1 in Python; the version must be the integer 1.
	("schema-float", _body(schema_version=1.0, providers={}, models=[]), "remote_schema_version"),
	("schema-true", _body(schema_version=True, providers={}, models=[]), "remote_schema_version"),
	("schema-string", _body(schema_version="1", providers={}, models=[]), "remote_schema_version"),
	("providers-list", _body(schema_version=1, providers=[], models=[]), "remote_malformed"),
	("providers-missing", _body(schema_version=1, models=[]), "remote_malformed"),
	("models-missing", _body(schema_version=1, providers={}), "remote_malformed"),
	("deep-nesting", b"[" * 100000, "remote_malformed"),
	("bad-utf8", b"\xff\xfe\x00{", "remote_malformed"),
]


@pytest.mark.parametrize("body, code", [row[1:] for row in PARSE_TABLE], ids=[row[0] for row in PARSE_TABLE])
def test_parse_remote_payload_table(body, code):
	document, issues = parse_remote_payload(body)

	if code is None:
		assert isinstance(document, dict)
		assert issues == ()
	else:
		assert document is None
		assert [(issue.code, issue.location) for issue in issues] == [(code, "payload")]


def test_a_bom_payload_parses_to_the_same_document():
	assert parse_remote_payload(b"\xef\xbb\xbf" + SERVER_BYTES) == parse_remote_payload(SERVER_BYTES)


def test_malformed_details_never_contain_the_body():
	_document, issues = parse_remote_payload(b'{"secret-token": [1,')

	assert "secret" not in issues[0].detail


def _accept(document, runnable_providers=SUPPORTED_PROVIDERS):
	return accept_remote_document(BundledSentinel(), document, runnable_providers=runnable_providers)


def _server_document():
	document = json.loads(SERVER_BYTES)
	document.pop("coseeings", None)
	return document


def test_a_valid_payload_is_accepted():
	catalog, issues = _accept(_server_document())

	assert catalog is not None
	assert has_local_items(catalog)
	assert issues == ()


def test_only_inactive_models_is_rejected():
	document = _server_document()
	for model in document["models"]:
		model["active"] = False

	catalog, issues = _accept(document)

	assert catalog is None
	assert [(issue.code, issue.location) for issue in issues] == [("remote_no_models", "payload")]


def test_only_unsupported_providers_is_rejected():
	catalog, issues = _accept(_server_document(), runnable_providers=frozenset())

	assert catalog is None
	assert [issue.code for issue in issues] == ["remote_no_models"]


def test_only_disallowed_hosts_is_rejected():
	document = _server_document()
	for provider in document["providers"].values():
		provider["url"] = "https://evil.test/v1"

	catalog, issues = _accept(document)

	assert catalog is None
	assert [issue.code for issue in issues] == ["remote_no_models"]


# (id, document, code). The cache hands accept_remote_document() an already
# parsed dict, so the section 8.3 document checks must live on that path too.
ACCEPT_DOCUMENT_TABLE = [
	("schema-2", {"schema_version": 2, "providers": {}, "models": []}, "remote_schema_version"),
	("schema-missing", {"providers": {}, "models": []}, "remote_schema_version"),
	("schema-text", {"schema_version": "v2", "providers": {}, "models": []}, "remote_schema_version"),
	("providers-list", {"schema_version": 1, "providers": [], "models": []}, "remote_malformed"),
	("models-missing", {"schema_version": 1, "providers": {}}, "remote_malformed"),
	("not-a-dict", ["schema_version", 1], "remote_malformed"),
]


@pytest.mark.parametrize(
	"document, code",
	[row[1:] for row in ACCEPT_DOCUMENT_TABLE],
	ids=[row[0] for row in ACCEPT_DOCUMENT_TABLE],
)
def test_accept_applies_the_document_checks(document, code):
	if isinstance(document, dict):
		# Fill the keys a row keeps well-formed with the real server data, so
		# only the row's own defect stands between it and a local model.
		good = _server_document()
		document = dict(document)
		for key in ("providers", "models"):
			if isinstance(document.get(key), type(good[key])):
				document[key] = good[key]

	catalog, issues = _accept(document)

	assert catalog is None
	assert [(issue.code, issue.location) for issue in issues] == [(code, "payload")]


@pytest.mark.parametrize("document, code", [row[1:] for row in ACCEPT_DOCUMENT_TABLE], ids=[row[0] for row in ACCEPT_DOCUMENT_TABLE])
def test_check_remote_document_matches_the_accept_path(document, code):
	assert [issue.code for issue in check_remote_document(document)] == [code]


def test_check_remote_document_passes_a_valid_document():
	assert check_remote_document(_server_document()) == ()
