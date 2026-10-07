import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

try:
    load_dotenv()
except PermissionError:
    # .env may be locked down to another user (e.g. root-only key storage
    # sitting in the app dir); config then comes from the environment
    # (systemd unit), so an unreadable .env is not fatal.
    pass

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://registry:registry@localhost:5432/registry",
)


class Base(DeclarativeBase):
    pass


engine = create_engine(DATABASE_URL, pool_size=5, max_overflow=10)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
