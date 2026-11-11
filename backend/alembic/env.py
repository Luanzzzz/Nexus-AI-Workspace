import asyncio

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import context
from app.db.base import Base
from app.db.session import database_url
from app.models.document import Document
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember

config = context.config

target_metadata = Base.metadata
registered_models = (Document, User, Workspace, WorkspaceMember)


# Aplica as migrations na conexão já aberta.
def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():
        context.run_migrations()


# roda a migration online
async def run_async_migrations():
    engine = create_async_engine(database_url, poolclass=NullPool)

    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


# O modo offline não abre conexão e não é suportado.
if context.is_offline_mode():
    raise RuntimeError("Offline mode is not supported")
else:
    asyncio.run(run_async_migrations())
