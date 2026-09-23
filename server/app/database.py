from urllib.parse import quote

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine

DB_USER = 'wordbridge'
DB_PASS = quote('wob@w125')
DB_HOST = 'wob-db'
DB_PORT = '3306'
DATABASE = 'WordBridge'
ENCODING = 'charset=utf8mb4'

SYNC_SQLALCHEMY_DATABASE_URL = 'mysql+mysqldb://{}:{}@{}:{}/{}?{}'.format(DB_USER, DB_PASS, DB_HOST, DB_PORT, DATABASE, ENCODING)
SYNC_SQLALCHEMY_DATABASE_URL = 'mysql+pymysql://{}:{}@{}:{}/{}?{}'.format(DB_USER, DB_PASS, DB_HOST, DB_PORT, DATABASE, ENCODING)
# SYNC_SQLALCHEMY_DATABASE_URL = 'sqlite+pysqlite:///../../data/test.db'
sync_engine = create_engine(SYNC_SQLALCHEMY_DATABASE_URL)

ASYNC_SQLALCHEMY_DATABASE_URL = 'mysql+aiomysql://{}:{}@{}:{}/{}?{}'.format(DB_USER, DB_PASS, DB_HOST, DB_PORT, DATABASE, ENCODING)
# ASYNC_SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///../../data/test.db"
async_engine = create_async_engine(ASYNC_SQLALCHEMY_DATABASE_URL)
