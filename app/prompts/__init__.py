from pathlib import Path

_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """Prompts are plain files named <purpose>_v<N>.md. The file name IS the version recorded with results."""
    return (_DIR / f"{name}.md").read_text(encoding="utf-8")


def clean(text: object) -> str:
    """Make untrusted text safe to place inside a tagged prompt section (it cannot close the tag)."""
    return str(text or "").replace("</", "<\\/").strip()
