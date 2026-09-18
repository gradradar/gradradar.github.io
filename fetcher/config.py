"""Tiny reader for the config files.

They only ever hold `key:` followed by a list of strings, so a 30-line parser
beats adding a PyYAML dependency - the fetcher runs with a bare Python install.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"


def load_lists(path: str | Path) -> dict[str, list[str]]:
    path = Path(path)
    if not path.is_absolute():
        path = CONFIG / path
    out: dict[str, list[str]] = {}
    current: str | None = None
    if not path.exists():
        return out

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = _strip_comment(line)
        if not stripped:
            continue
        if stripped.startswith("- "):
            if current is not None:
                value = _unquote(stripped[2:].strip())
                if value and value != "[]":
                    out[current].append(value)
        elif stripped.endswith(":"):
            current = stripped[:-1].strip()
            out.setdefault(current, [])
        elif ":" in stripped:
            key, _, value = stripped.partition(":")
            current = key.strip()
            out.setdefault(current, [])
            value = _unquote(value.strip())
            if value and value not in ("[]", "|", ">"):
                out[current].append(value)
    return out


def _strip_comment(line: str) -> str:
    """Drop trailing comments, respecting quotes."""
    out, quote = [], None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).strip()


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value
