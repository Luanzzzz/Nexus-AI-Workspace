"""Utilitários de segurança.

O hash de senha usa Argon2id. Os parâmetros são explícitos e iguais aos
defaults atuais do argon2-cffi (m=64MiB, t=3, p=4). Não os altere sem
benchmark na infraestrutura de destino.
"""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST_KIB = 65536
ARGON2_PARALLELISM = 4
ARGON2_HASH_LEN = 32
ARGON2_SALT_LEN = 16

_password_hasher = PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_COST_KIB,
    parallelism=ARGON2_PARALLELISM,
    hash_len=ARGON2_HASH_LEN,
    salt_len=ARGON2_SALT_LEN,
)


def hash_password(password: str) -> str:
    """Gera um hash de senha."""
    return _password_hasher.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Verifica se a senha corresponde ao hash."""
    try:
        return _password_hasher.verify(hashed_password, password)
    except VerifyMismatchError:
        return False
