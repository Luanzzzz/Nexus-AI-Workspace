import pytest
from argon2.exceptions import InvalidHashError

from app.core.security import hash_password, verify_password

_PASSWORD_CASES = [
    ("123456", "654321"),
    ("senha123", "123senha"),
    ("senha123456", "senha654321"),
    ("senha123456789", "senha987654321"),
    ("senha1234567890", "senha0987654321"),
    ("senha12345678901234567890", "09876543210987654321senha"),
    (
        "senha123456789012345678901234567890",
        "098765432109876543210987654321senha",
    ),
]


@pytest.mark.parametrize(("password", "wrong_password"), _PASSWORD_CASES)
def test_verify_password_accepts_correct_password(password, wrong_password):
    hashed_password = hash_password(password)
    assert verify_password(password, hashed_password)


@pytest.mark.parametrize(("password", "wrong_password"), _PASSWORD_CASES)
def test_verify_password_rejects_wrong_password(password, wrong_password):
    hashed_password = hash_password(password)
    assert not verify_password(wrong_password, hashed_password)


# 3. teste hash de senha para a mesma senha
# deve gerar hashes diferentes
def test_hash_password_generates_different_hashes_for_same_password():
    password = "123456"
    hashed_password1 = hash_password(password)
    hashed_password2 = hash_password(password)
    assert hashed_password1 != hashed_password2
    assert hashed_password1.startswith("$argon2id$")
    assert hashed_password2.startswith("$argon2id$")
    assert verify_password(password, hashed_password1)
    assert verify_password(password, hashed_password2)


# 4. teste verificação de senha com hash corrompido
def test_verify_password_rejects_corrupted_hash():
    with pytest.raises(InvalidHashError):
        verify_password("senha-ficticia", "hash_corrompido")
