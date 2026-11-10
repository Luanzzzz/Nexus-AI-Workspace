import pytest
from argon2 import Type, extract_parameters
from argon2.exceptions import InvalidHashError

from app.core.security import (
    ARGON2_HASH_LEN,
    ARGON2_MEMORY_COST_KIB,
    ARGON2_PARALLELISM,
    ARGON2_SALT_LEN,
    ARGON2_TIME_COST,
    hash_password,
    verify_password,
)

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


def test_hash_password_generates_different_hashes_for_same_password():
    password = "123456"
    hashed_password1 = hash_password(password)
    hashed_password2 = hash_password(password)
    assert hashed_password1 != hashed_password2
    assert hashed_password1.startswith("$argon2id$")
    assert hashed_password2.startswith("$argon2id$")
    assert verify_password(password, hashed_password1)
    assert verify_password(password, hashed_password2)


def test_verify_password_rejects_corrupted_hash():
    with pytest.raises(InvalidHashError):
        verify_password("senha-ficticia", "hash_corrompido")


def test_hash_password_uses_explicit_argon2id_parameters():
    hashed = hash_password("x")
    parameters = extract_parameters(hashed)

    assert parameters.type is Type.ID
    assert parameters.version == 19
    assert parameters.time_cost == ARGON2_TIME_COST == 3
    assert parameters.memory_cost == ARGON2_MEMORY_COST_KIB == 65536
    assert parameters.parallelism == ARGON2_PARALLELISM == 4
    assert parameters.hash_len == ARGON2_HASH_LEN == 32
    assert parameters.salt_len == ARGON2_SALT_LEN == 16
    assert parameters.memory_cost >= 19456
    assert parameters.time_cost >= 2
