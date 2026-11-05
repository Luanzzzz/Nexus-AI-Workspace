"""Utilitários de segurança.

O hash de senha usa Argon2id. A instância do hasher concentra a configuração
do algoritmo; cada chamada de hash gera um salt próprio.
"""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_password_hasher = PasswordHasher()


# Hash de senha
def hash_password(password: str) -> str:
    """Gera um hash de senha."""
    return _password_hasher.hash(password)


# Verificação de senha
def verify_password(password: str, hashed_password: str) -> bool:
    """Verifica se a senha corresponde ao hash."""
    try:
        return _password_hasher.verify(hashed_password, password)
    except VerifyMismatchError:
        return False
