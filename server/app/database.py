from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine

from .settings import SETTINGS

# The connection details come from DB_USER, DB_PASS, DB_HOST, DB_PORT and
# DATABASE (see app/settings.py); URL.create escapes the credentials.
SYNC_SQLALCHEMY_DATABASE_URL = SETTINGS.database_url("mysql+pymysql")
sync_engine = create_engine(SYNC_SQLALCHEMY_DATABASE_URL)

ASYNC_SQLALCHEMY_DATABASE_URL = SETTINGS.database_url("mysql+aiomysql")
async_engine = create_async_engine(ASYNC_SQLALCHEMY_DATABASE_URL)
