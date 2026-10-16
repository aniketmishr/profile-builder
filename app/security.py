import hashlib
import hmac
import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings

# API keys look like pk_<8 char prefix>_<32 char secret>. Only the sha256 is stored.
# Keys are high-entropy random strings, so a fast hash is appropriate (no need for bcrypt).


def generate_api_key() -> tuple[str, str, str]:
    prefix = secrets.token_hex(4)
    full = f"pk_{prefix}_{secrets.token_urlsafe(24)}"
    return full, prefix, hash_key(full)


def hash_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode()).hexdigest()


def parse_prefix(full_key: str) -> str | None:
    parts = full_key.split("_", 2)
    if len(parts) != 3 or parts[0] != "pk":
        return None
    return parts[1]


def keys_match(full_key: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_key(full_key), stored_hash)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_token_secret, salt="chat-session")


def make_session_token(session_id: str, tenant_id: str) -> str:
    return _serializer().dumps({"sid": session_id, "tid": tenant_id})


def verify_session_token(token: str) -> dict | None:
    try:
        return _serializer().loads(token, max_age=get_settings().session_token_ttl_seconds)
    except (BadSignature, SignatureExpired):
        return None
