from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models.user import User


@pytest.mark.integration
@pytest.mark.asyncio
async def test_user_model():
    email = f"test-{uuid4().hex}@example.com"

    async with SessionLocal() as session:
        user = User(
            email=email,
            password_hash="fake-password-hash",
            name="Test User",
        )
        session.add(user)
        await session.flush()

        assert user.id is not None
        assert user.email == email
        assert user.password_hash == "fake-password-hash"
        assert user.name == "Test User"

        await session.rollback()
