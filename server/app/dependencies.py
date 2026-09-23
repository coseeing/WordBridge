from sqlalchemy.orm import sessionmaker

from .database import sync_engine as engine

Session = sessionmaker(bind=engine)

def get_db():
	db = Session()
	try:
		yield db
	finally:
		db.close()
