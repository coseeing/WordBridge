"""Add SSO user fields and remove passwords

Revision ID: 20260923_sso_user
Revises: dad5039f4770
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '20260923_sso_user'
down_revision: Union[str, None] = 'dad5039f4770'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	"""Upgrade schema."""
	op.add_column('user', sa.Column('sso_sub', sa.String(length=255), nullable=True))
	op.add_column(
		'user',
		sa.Column('email_verified', sa.Boolean(), nullable=False, server_default=sa.false()),
	)
	op.alter_column(
		'user',
		'account',
		existing_type=mysql.VARCHAR(length=30),
		type_=mysql.VARCHAR(length=254),
		existing_nullable=False,
	)
	op.create_index(op.f('ix_user_sso_sub'), 'user', ['sso_sub'], unique=True)
	op.drop_column('user', 'password')


def downgrade() -> None:
	"""Downgrade schema."""
	op.add_column(
		'user',
		sa.Column('password', mysql.VARCHAR(length=128), nullable=True),
	)
	op.drop_index(op.f('ix_user_sso_sub'), table_name='user')
	op.alter_column(
		'user',
		'account',
		existing_type=mysql.VARCHAR(length=254),
		type_=mysql.VARCHAR(length=30),
		existing_nullable=False,
	)
	op.drop_column('user', 'email_verified')
	op.drop_column('user', 'sso_sub')
