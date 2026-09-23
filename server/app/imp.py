import csv
from datetime import datetime, timedelta
import os


from sqlalchemy import select, text

from sqlalchemy.orm import sessionmaker, selectinload

from .database import sync_engine as engine
from .baseModel import Base
from .models.models import Interaction
from .user.models import User

BASE_DIR = os.path.dirname(__file__)

Base.metadata.create_all(bind=engine)
Session = sessionmaker(bind=engine)

def main():
	with Session() as session:
		with session.begin():
			# SSO-linked users (Task 1: no password column). sso_sub is left
			# unset here -- these rows are linked to a verified SSO identity
			# on first login (see app/user/linking.py), not seeded up front.
			users = [
				User(
					name="Coseeing",
					account="coseeings@coseeing.org",
					is_active=True,
					quota=0.1,
				),
				User(
					name="Test User 1",
					account="user1@example.org",
					is_active=True,
					quota=0.1,
				),
				User(
					name="Test User 2",
					account="user2@example.org",
					is_active=True,
					quota=0.1,
				),
				User(
					name="design",
					account="ddesign@coseeing.org",
					is_active=True,
					quota=0.1,
				),
				User(
					name="Test User 3",
					account="user3@example.org",
					is_active=True,
					quota=0.1,
				),
			]
			session.add_all(users)

	# Querying records with join and loading related entities
	with Session() as session:
		with session.begin():
			stmt = select(User, Interaction).join(User.interactions, isouter=True).options(selectinload(User.interactions))
			result = session.execute(stmt)
			for user, interaction in result.all():
				print(user, interaction)

main()
