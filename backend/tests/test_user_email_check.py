"""CHECK de email canônico.

Quem grava direto no model, sem passar pelo schema, continua sujeito
à restrição. O teste só faz flush e rollback, como a Fase 1.5.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.models.user import User


@pytest.mark.integration
@pytest.mark.asyncio
async def test_check_rejects_uppercase_email_on_direct_insert():
    email = f"Maiuscula-{uuid4().hex}@Example.com"

    async with SessionLocal() as session:
        session.add(
            User(
                email=email,
                name="Pessoa",
                password_hash="hash-ja-pronto",
            ),
        )
        with pytest.raises(IntegrityError) as exc_info:
            await session.flush()

        assert "ck_users_email_lowercase" in str(exc_info.value.orig)
        await session.rollback()

    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email.lower()))
        assert result.scalar_one_or_none() is None
        await session.rollback()
