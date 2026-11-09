"""Exceções de domínio da aplicação."""


class DuplicateEmailError(Exception):
    # O email canônico já pertence a um usuário.
    # Sem senha, sem hash e sem o endereço: o router escolhe o HTTP 409.
    pass
