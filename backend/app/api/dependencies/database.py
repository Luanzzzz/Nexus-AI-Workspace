"""implemente uma função chamada get_db() seguindo estas orientações:
- Deve ser assíncrona (async def).
- Deve utilizar SessionLocal do nosso app.db.session.
- Deve abrir a sessão com async with.
- Deve disponibilizar a sessão utilizando yield, não return.
- Deve utilizar a anotação de retorno AsyncIterator[AsyncSession]
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session