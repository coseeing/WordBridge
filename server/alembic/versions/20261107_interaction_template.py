"""Index the quota queries, record the template, widen version, drop category

Revision ID: 20261107_interaction_template
Revises: 20260923_sso_user
Create Date: 2026-11-07 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "20261107_interaction_template"
down_revision: str | None = "20260923_sso_user"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
	"""Upgrade schema."""
	# The single-column user_id index behind the foreign key stays (D2). The
	# one MariaDB created for the foreign key is silently dropped as soon as
	# another index starts with user_id, and the downgrade could then not
	# drop that index (error 1553). Rebuilt explicitly, it stays.
	op.execute("ALTER TABLE interaction DROP INDEX user_id, ADD INDEX user_id (user_id)")
	# The quota queries (app/main.py _sum_cost).
	op.create_index("ix_interaction_user_id_request_time", "interaction", ["user_id", "request_time"])
	op.create_index("ix_interaction_ip_address_request_time", "interaction", ["ip_address", "request_time"])
	# version now holds the add-on version, e.g. 2026.11.1.
	op.alter_column(
		"interaction",
		"version",
		existing_type=sa.String(length=8),
		type_=sa.String(length=32),
		existing_nullable=False,
	)
	# Rows written before this migration did not record their template;
	# they get "". The default is only for those rows.
	op.add_column(
		"interaction",
		sa.Column("template", sa.String(length=64), nullable=False, server_default=""),
	)
	op.alter_column(
		"interaction",
		"template",
		existing_type=sa.String(length=64),
		existing_nullable=False,
		server_default=None,
	)
	# Every stored value was the hard-coded "1".
	op.drop_column("interaction", "category")


def downgrade() -> None:
	"""Downgrade schema.

	MariaDB cannot roll DDL back, so the one step that can fail on data,
	shrinking version back to 8 characters, is checked before any change.
	"""
	if not context.is_offline_mode():
		long_versions = (
			op.get_bind()
			.execute(sa.text("SELECT COUNT(*) FROM interaction WHERE CHAR_LENGTH(version) > 8"))
			.scalar()
		)
		if long_versions:
			raise RuntimeError(
				f"{long_versions} interaction rows have a version longer than 8 characters, "
				"which the previous schema cannot hold. Restore the backup taken before the "
				"upgrade, or shorten those values, then downgrade again. Nothing was changed.",
			)
	# The index drops can fail on a foreign key, so they go before any
	# column change.
	op.drop_index("ix_interaction_ip_address_request_time", table_name="interaction")
	op.drop_index("ix_interaction_user_id_request_time", table_name="interaction")
	op.add_column("interaction", sa.Column("category", sa.String(length=8), nullable=True))
	op.drop_column("interaction", "template")
	op.alter_column(
		"interaction",
		"version",
		existing_type=sa.String(length=32),
		type_=sa.String(length=8),
		existing_nullable=False,
	)
