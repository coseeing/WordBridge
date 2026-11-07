"""`alembic upgrade head --sql` prints the migration SQL without a database.

Deployment reviews that SQL before running the migration. Offline mode
needs only the dialect, which comes from the same settings online mode
uses; it never connects.
"""

import os
import subprocess
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent


def run_alembic_sql(*args, **environ):
	# conftest.py has already put every setting app.settings needs into
	# os.environ; the subprocess inherits them, with `environ` on top.
	return subprocess.run(
		[sys.executable, "-m", "alembic", *args],
		cwd=SERVER,
		env=dict(os.environ, **environ),
		capture_output=True,
		text=True,
		timeout=120,
		check=False,
	)


def test_offline_upgrade_prints_the_sql():
	result = run_alembic_sql("upgrade", "head", "--sql")

	assert result.returncode == 0, result.stderr
	assert "ALTER TABLE user ADD COLUMN sso_sub" in result.stdout
	assert "UPDATE alembic_version SET version_num='20260923_sso_user'" in result.stdout
	assert "placeholder" not in result.stderr


def test_offline_sql_never_shows_the_database_password():
	# The SQL is meant to be pasted into a review; the password must not be.
	password = "m6-Pa55word-only-in-this-test"

	result = run_alembic_sql("upgrade", "head", "--sql", DB_PASS=password)

	assert result.returncode == 0, result.stderr
	assert "CREATE INDEX ix_interaction_user_id_request_time" in result.stdout
	assert password not in result.stdout
	assert password not in result.stderr


def test_offline_sql_contains_the_new_migration():
	result = run_alembic_sql("upgrade", "20260923_sso_user:head", "--sql")

	assert result.returncode == 0, result.stderr
	assert "ALTER TABLE interaction DROP INDEX user_id, ADD INDEX user_id (user_id)" in result.stdout
	assert (
		"CREATE INDEX ix_interaction_user_id_request_time ON interaction (user_id, request_time)"
		in result.stdout
	)
	assert (
		"CREATE INDEX ix_interaction_ip_address_request_time ON interaction (ip_address, request_time)"
		in result.stdout
	)
	assert "ALTER TABLE interaction MODIFY version VARCHAR(32) NOT NULL" in result.stdout
	assert "ALTER TABLE interaction DROP COLUMN category" in result.stdout
	assert "version_num='20261107_interaction_template'" in result.stdout
