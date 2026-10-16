import secrets
import time


def new_id(prefix: str) -> str:
    """Time-ordered id like ss_0199abc123ef4f5a6b7c8d. Sortable, no extra dependency."""
    return f"{prefix}_{int(time.time() * 1000):012x}{secrets.token_hex(5)}"
