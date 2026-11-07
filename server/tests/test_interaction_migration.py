"""The interaction migration declares what the model declares.

The server tests run on SQLite and cannot run a MySQL migration, so the
migration's operations are recorded and compared with the model. A real
MariaDB run is part of the deployment checks.
"""

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.models import Interaction

SERVER = Path(__file__).resolve().parent.parent
MIGRATION = SERVER / "alembic" / "versions" / "20261107_interaction_template.py"
REBUILD_USER_ID_INDEX = "ALTER TABLE interaction DROP INDEX user_id, ADD INDEX user_id (user_id)"


class _Recorder:
	"""Stands in for alembic's `op`, recording every call."""

	def __init__(self, long_versions=0):
		self.calls = []
		self.queries = []
		self.long_versions = long_versions

	def get_bind(self):
		return SimpleNamespace(execute=self._query)

	def _query(self, statement):
		self.queries.append(str(statement))
		return SimpleNamespace(scalar=lambda: self.long_versions)

	def __getattr__(self, name):
		return lambda *args, **kwargs: self.calls.append((name, args, kwargs))


def _migration(recorder):
	spec = importlib.util.spec_from_file_location("migration_under_test", MIGRATION)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	module.op = recorder
	module.context = SimpleNamespace(is_offline_mode=lambda: False)
	return module


def _calls(recorder, name):
	return [(args, kwargs) for called, args, kwargs in recorder.calls if called == name]


def test_upgrade_matches_the_model():
	recorder = _Recorder()
	migration = _migration(recorder)

	migration.upgrade()

	created = {args[0]: (args[1], tuple(args[2])) for args, _ in _calls(recorder, "create_index")}
	model = {
		index.name: ("interaction", tuple(column.name for column in index.columns))
		for index in Interaction.__table__.indexes
	}
	assert model == {
		"ix_interaction_user_id_request_time": ("interaction", ("user_id", "request_time")),
		"ix_interaction_ip_address_request_time": ("interaction", ("ip_address", "request_time")),
	}
	assert {name: created[name] for name in model} == model

	[(args, kwargs)] = [call for call in _calls(recorder, "alter_column") if call[0][1] == "version"]
	assert kwargs["type_"].length == 32 == Interaction.__table__.c.version.type.length
	assert kwargs["existing_nullable"] is False

	[(args, kwargs)] = _calls(recorder, "add_column")
	column = args[1]
	assert (args[0], column.name, column.type.length, column.nullable) == (
		"interaction",
		"template",
		64,
		False,
	)
	# The "" default only fills the existing rows; new rows must name their
	# template, as the model has no default.
	assert column.server_default.arg == ""
	[(args, kwargs)] = [call for call in _calls(recorder, "alter_column") if call[0][1] == "template"]
	assert args == ("interaction", "template")
	assert "server_default" in kwargs
	assert kwargs["server_default"] is None
	assert Interaction.__table__.c.template.server_default is None
	assert Interaction.__table__.c.template.type.length == 64
	assert Interaction.__table__.c.template.nullable is False

	assert (("interaction", "category"), {}) in _calls(recorder, "drop_column")
	assert migration.down_revision == "20260923_sso_user"
	assert migration.revision == "20261107_interaction_template"


def test_upgrade_keeps_the_user_id_index_first():
	# MariaDB silently drops the index it created for the user_id foreign
	# key once another index starts with user_id; rebuilt explicitly
	# first, it stays (D2), and the downgrade can drop the composite one.
	recorder = _Recorder()

	_migration(recorder).upgrade()

	name, args, _ = recorder.calls[0]
	assert (name, str(args[0])) == ("execute", REBUILD_USER_ID_INDEX)


def test_downgrade_restores_the_previous_shape():
	recorder = _Recorder(long_versions=0)

	_migration(recorder).downgrade()

	dropped = {args[0] for args, _ in _calls(recorder, "drop_index")}
	assert dropped == {"ix_interaction_user_id_request_time", "ix_interaction_ip_address_request_time"}
	[(args, kwargs)] = [call for call in _calls(recorder, "alter_column") if call[0][1] == "version"]
	assert kwargs["type_"].length == 8
	[(args, _)] = _calls(recorder, "add_column")
	assert (args[1].name, args[1].type.length, args[1].nullable) == ("category", 8, True)
	assert (("interaction", "template"), {}) in _calls(recorder, "drop_column")
	# The index drops can fail on a foreign key; they come before any column
	# change, so such a failure leaves the columns untouched.
	names = [name for name, _, _ in recorder.calls]
	assert names[:2] == ["drop_index", "drop_index"]


def test_downgrade_refuses_long_versions_before_any_ddl():
	recorder = _Recorder(long_versions=3)

	with pytest.raises(RuntimeError, match="3"):
		_migration(recorder).downgrade()

	assert recorder.calls == []
	# The previous schema holds 8 characters: the guard counts exactly the
	# rows that would not fit.
	assert recorder.queries == ["SELECT COUNT(*) FROM interaction WHERE CHAR_LENGTH(version) > 8"]


def test_alembic_env_maps_every_model():
	# Autogenerate and `alembic check` compare against Base.metadata, which
	# only knows the tables of the model modules that were imported.
	tree = ast.parse((SERVER / "alembic" / "env.py").read_text(encoding="utf-8"))
	imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
	imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

	assert {"app.models.models", "app.user.models"} <= imported
