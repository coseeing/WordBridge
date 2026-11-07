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


def run_alembic_sql(*args):
	# conftest.py has already put every setting app.settings needs into
	# os.environ; the subprocess inherits them.
	return subprocess.run(
		[sys.executable, "-m", "alembic", *args],
		cwd=SERVER,
		env=dict(os.environ),
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
