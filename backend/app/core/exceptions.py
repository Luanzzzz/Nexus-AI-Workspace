"""Exceções de domínio da aplicação."""


class DuplicateEmailError(Exception):
    # O email canônico já pertence a um usuário.
    # Sem senha, sem hash e sem o endereço: o router responde como no sucesso.
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


class DuplicateSlugError(Exception):
    # O slug do workspace já existe (UNIQUE global, ADR 0001).
    # Sem o slug na mensagem: o handler responde 409 genérico.
    pass


class UnsupportedDocumentTypeError(Exception):
    # Extensão ou Content-Type fora da lista permitida (415).
    pass


class InvalidDocumentError(Exception):
    # Nome inválido, arquivo vazio ou conteúdo que não confere com o tipo (422).
    pass


class DocumentTooLargeError(Exception):
    # O upload passou do limite de tamanho (413).
    pass


class DocumentUploadError(Exception):
    # Falha interna no upload (storage ou banco). Mensagem fixa: sem caminho,
    # chave de storage nem nome de arquivo. O handler responde 500 genérico.
    def __init__(self) -> None:
        super().__init__("Falha interna ao gravar o documento.")


class StorageError(Exception):
    # Chave inválida ou caminho inseguro no storage local. Sem caminho na mensagem.
    pass
