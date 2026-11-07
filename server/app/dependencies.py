"""Database session dependencies.

There are two on purpose. The routes this server is built around
(/proofreader, /feedback, the SSO user lookup) are synchronous, like the
add-on code they run, and use get_db. The superuser CRUD routes /users and
/interactions come from fastcrud's crud_router, which only works with an
async session, so they use get_async_session on the async engine.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker

from .database import async_engine, sync_engine

Session = sessionmaker(bind=sync_engine)
async_session = async_sessionmaker(async_engine, expire_on_commit=False)


def get_db():
	db = Session()
	try:
		yield db
	finally:
		db.close()


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
	async with async_session() as session:
		yield session
