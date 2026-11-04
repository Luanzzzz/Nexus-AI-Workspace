"""Database session management.

Engine and session wiring will be implemented later.
"""

from sqlalchemy import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings

database_url = URL.create(
    drivername="postgresql+psycopg",
    username=settings.postgres_user,
    password=settings.postgres_password,
    host=settings.postgres_host,
    port=settings.postgres_port,
    database=settings.postgres_db,
)

engine = create_async_engine(database_url)

SessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)
