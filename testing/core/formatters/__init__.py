from __future__ import annotations

from typing import Dict

from .base import Formatter
from .kr_default import get_formatter as _kr_default


_FORMATTERS: Dict[str, Formatter] = {
    "kr_default": _kr_default(),
}


def get_formatter(style_id: str) -> Formatter:
    if style_id not in _FORMATTERS:
        raise KeyError(f"Unknown style_id: {style_id}")
    return _FORMATTERS[style_id]


def list_formatters() -> Dict[str, str]:
    """style_id -> display_name"""
    return {k: v.display_name for k, v in _FORMATTERS.items()}
