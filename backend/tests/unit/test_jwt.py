"""Testes de emissão/validação de JWT, sem banco de dados."""

import base64
import hashlib
import hmac
import inspect
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core import tokens
from app.core.config import settings
from app.core.tokens import (
    AccessTokenClaims,
    InvalidTokenError,
    create_access_token,
    decode_access_token,
)

SECRET = settings.jwt_secret_key.get_secret_value()
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _payload(**overrides):
    payload = {
        "sub": "42",
        "iat": int(NOW.timestamp()),
        "exp": int((NOW + timedelta(minutes=30)).timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "token_type": "access",
    }
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def _encode(payload, key=SECRET, algorithm="HS256"):
    return jwt.encode(payload, key, algorithm=algorithm)


def _forge(payload) -> str:
    """Token HS256 assinado com a chave correta, sem as checagens do jwt.encode."""
    signing_input = f"{_b64({'alg': 'HS256', 'typ': 'JWT'})}.{_b64(payload)}"
    digest = hmac.new(SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    signature = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return f"{signing_input}.{signature}"


def _fresh_payload(**overrides):
    """Payload válido relativo ao relógio real (para decode, que usa o agora)."""
    now = datetime.now(UTC)
    fresh = {
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=30)).timestamp()),
    }
    return _payload(**{**fresh, **overrides})


def _b64(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_valid_token_roundtrip():
    now = datetime.now(UTC)
    claims = decode_access_token(create_access_token(42, now=now))

    assert isinstance(claims, AccessTokenClaims)
    assert claims.user_id == 42
    assert claims.expires_at - claims.issued_at == timedelta(minutes=30)


def test_token_payload_has_expected_claims_only():
    token = create_access_token(7, now=NOW)

    payload = jwt.decode(token, options={"verify_signature": False})

    assert payload == {
        "sub": "7",
        "iat": int(NOW.timestamp()),
        "exp": int((NOW + timedelta(minutes=30)).timestamp()),
        "iss": "nexus-ai-workspace",
        "aud": "nexus-api",
        "token_type": "access",
    }
    assert "email" not in payload
    assert "password" not in payload


def test_create_rejects_naive_datetime():
    with pytest.raises(ValueError):
        create_access_token(1, now=datetime(2026, 1, 1))


def test_expired_token_rejected_with_controlled_timestamps():
    token = create_access_token(42, now=datetime.now(UTC) - timedelta(minutes=31))

    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_token_not_yet_expired_accepted_near_limit():
    token = create_access_token(42, now=datetime.now(UTC) - timedelta(minutes=29))

    assert decode_access_token(token).user_id == 42


def test_tampered_signature_rejected():
    token = create_access_token(42, now=datetime.now(UTC))
    header, body, signature = token.split(".")
    flipped = "A" if signature[0] != "A" else "B"

    with pytest.raises(InvalidTokenError):
        decode_access_token(f"{header}.{body}.{flipped}{signature[1:]}")


def test_tampered_payload_rejected():
    token = create_access_token(42, now=datetime.now(UTC))
    header, _, signature = token.split(".")
    forged = _b64(_fresh_payload(sub="1"))

    with pytest.raises(InvalidTokenError):
        decode_access_token(f"{header}.{forged}.{signature}")


def test_wrong_key_rejected():
    token = _encode(_fresh_payload(), key="x" * 40)

    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_valid_payload_with_correct_key_is_accepted():
    assert decode_access_token(_encode(_fresh_payload())).user_id == 42


@pytest.mark.parametrize("claim", ["exp", "sub", "iat", "iss", "aud", "token_type"])
def test_missing_required_claim_rejected(claim):
    token = _encode(_fresh_payload(**{claim: None}))

    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


@pytest.mark.parametrize("sub", ["abc", "0", "-1", "1.5", "", " 1", "+1", "１２"])
def test_invalid_subject_rejected(sub):
    with pytest.raises(InvalidTokenError):
        decode_access_token(_encode(_fresh_payload(sub=sub)))


def test_non_string_subject_rejected():
    with pytest.raises(InvalidTokenError):
        decode_access_token(_encode(_fresh_payload(sub=42)))


@pytest.mark.parametrize(
    "sub",
    [
        "0",
        "-1",
        " 1",
        "1 ",
        "1.0",
        "2147483648",
        "9" * 5000,
        "1" * 20,
        1,
        True,
    ],
    ids=repr,
)
def test_malformed_subject_with_valid_signature_rejected(sub):
    token = _encode(_fresh_payload(sub=sub))

    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_max_user_id_subject_accepted():
    assert decode_access_token(_encode(_fresh_payload(sub="2147483647"))).user_id == (
        2**31 - 1
    )


def _ts():
    return int(datetime.now(UTC).timestamp())


@pytest.mark.parametrize(
    "overrides",
    [
        {"iat": str(_ts())},
        {"exp": str(_ts() + 600)},
        {"exp": 10**20},
        {"exp": 253_402_300_800},
        {"iat": _ts() + 0.0},
        {"exp": _ts() + 600.5},
        {"iat": True},
        {"exp": True},
        {"iat": 0},
        {"iat": -1},
    ],
    ids=repr,
)
def test_malformed_timestamps_with_valid_signature_rejected(overrides):
    with pytest.raises(InvalidTokenError) as exc_info:
        decode_access_token(_encode(_fresh_payload(**overrides)))

    assert exc_info.value.__cause__ is None


@pytest.mark.parametrize(
    "claim", ["iat", "exp", "iss", "aud", "nbf", "token_type", "sub"]
)
@pytest.mark.parametrize("value", [[], {}], ids=["list", "dict"])
def test_non_scalar_claims_with_valid_signature_rejected(claim, value):
    # jwt.encode recusa iss não-string; assina na mão para forjar o token.
    token = _forge(_fresh_payload(**{claim: value}))

    with pytest.raises(InvalidTokenError) as exc_info:
        decode_access_token(token)

    assert exc_info.value.__cause__ is None
    assert str(exc_info.value) == "Token inválido"


def test_type_error_from_pyjwt_decode_maps_to_invalid_token(monkeypatch):
    def raise_type_error(*args, **kwargs):
        raise TypeError("claim com tipo incompatível")

    monkeypatch.setattr(tokens.jwt, "decode", raise_type_error)

    with pytest.raises(InvalidTokenError) as exc_info:
        decode_access_token("a.b.c")

    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True


def test_exp_not_after_iat_rejected():
    # Via decode, exp <= iat com exp no futuro exigiria iat no futuro; o PyJWT
    # (iat no futuro) rejeita antes. Cobre a regra diretamente.
    with pytest.raises(InvalidTokenError):
        tokens._parse_timestamps(_ts(), _ts() - 10)


@pytest.mark.parametrize("user_id", [0, -1, 2**31, True, 1.5, "1", None])
def test_create_rejects_invalid_user_id(user_id):
    with pytest.raises(ValueError):
        create_access_token(user_id, now=NOW)


def test_wrong_issuer_rejected():
    with pytest.raises(InvalidTokenError):
        decode_access_token(_encode(_fresh_payload(iss="outro-emissor")))


def test_wrong_audience_rejected():
    with pytest.raises(InvalidTokenError):
        decode_access_token(_encode(_fresh_payload(aud="outra-api")))


@pytest.mark.parametrize("token_type", ["refresh", "ACCESS", "", 1])
def test_wrong_token_type_rejected(token_type):
    with pytest.raises(InvalidTokenError):
        decode_access_token(_encode(_fresh_payload(token_type=token_type)))


def test_hs512_algorithm_rejected():
    # Chave com >= 64 bytes: evita o InsecureKeyLengthWarning do PyJWT.
    key = "k" * 64
    with pytest.raises(InvalidTokenError):
        decode_access_token(_encode(_fresh_payload(), key=key, algorithm="HS512"))


def test_alg_none_rejected():
    header = _b64({"alg": "none", "typ": "JWT"})
    token = f"{header}.{_b64(_fresh_payload())}."

    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


@pytest.mark.parametrize("token", ["", "abc", "a.b", "a.b.c", "....", "💥"])
def test_malformed_token_rejected(token):
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_invalid_token_error_message_is_generic():
    with pytest.raises(InvalidTokenError) as exc_info:
        decode_access_token(_encode(_fresh_payload(), key="x" * 40))

    assert str(exc_info.value) == "Token inválido"
    assert exc_info.value.__cause__ is None


def test_decoding_does_not_skip_signature_verification():
    # Garante que o decode da aplicação nunca desliga a verificação.
    source = inspect.getsource(tokens)
    assert "verify_signature" not in source
    assert "verify=False" not in source
