"""Exceções de domínio da aplicação."""


class DuplicateEmailError(Exception):
    # O email canônico já pertence a um usuário.
    # Sem senha, sem hash e sem o endereço: o router escolhe o HTTP 409.
    pass


class InvalidCredentialsError(Exception):
    # Email ou senha não conferem (ou conta inativa).
    # Mensagem fixa e genérica: não revela qual dos casos ocorreu.
    def __init__(self) -> None:
        super().__init__("Credenciais inválidas.")


class CredentialVerificationError(Exception):
    # Falha interna ao verificar a senha (ex.: hash armazenado corrompido).
    # Não é erro do cliente; a mensagem não carrega hash nem senha.
    def __init__(self) -> None:
        super().__init__("Falha interna ao verificar credenciais.")
