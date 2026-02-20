from __future__ import annotations

import re
from typing import List, Sequence, Literal, Optional

from .model import Record
from .formatters import get_formatter
from .formatters.base import FormatOptions

# ✅ NEW
from .csl.adapter import records_to_csl_items
from .csl.renderer import render_bibliography_text


_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^0-9A-Za-z가-힣]+")


def _norm_key(s: str) -> str:
    s = (s or "").replace("\u00a0", " ").strip().lower()
    s = _SPACE_RE.sub(" ", s)
    s = _PUNCT_RE.sub("", s)
    return s


SortMode = Literal["none", "author_year", "year_author", "title"]


def sort_records(records: Sequence[Record], mode: SortMode) -> List[Record]:
    recs = list(records)
    if mode == "none":
        return recs

    def first_author(r: Record) -> str:
        return _norm_key(r.first_author_display() or "")

    def title(r: Record) -> str:
        return _norm_key(r.title or "")

    def year(r: Record) -> int:
        return int(r.year) if isinstance(r.year, int) else 9999

    if mode == "author_year":
        recs.sort(key=lambda r: (first_author(r), year(r), title(r)))
    elif mode == "year_author":
        recs.sort(key=lambda r: (year(r), first_author(r), title(r)))
    elif mode == "title":
        recs.sort(key=lambda r: (title(r), year(r), first_author(r)))
    else:
        raise ValueError(f"Unknown sort mode: {mode}")

    return recs


def _parse_style_selector(style_id: str) -> tuple[str, Optional[str]]:
    """
    Returns (kind, value)
      - kind="builtin", value="kr_default"
      - kind="csl", value="/abs/path/to/style.csl"
    하위호환:
      - "kr_default" 같은 값은 builtin으로 처리
    """
    if style_id.startswith("builtin:"):
        return "builtin", style_id.split(":", 1)[1]
    if style_id.startswith("csl:"):
        return "csl", style_id.split(":", 1)[1]
    # backward-compatible: treat as builtin id
    return "builtin", style_id


def format_references(
    records: Sequence[Record],
    *,
    style_id: str = "kr_default",
    sort_mode: SortMode = "author_year",
    opts: FormatOptions | None = None,
    # CSL options (optional now, expand later)
    csl_locale: str = "ko-KR",
) -> str:
    """
    Returns a plain text reference list (lines separated by \\n).

    style_id 지원 형태:
      - "kr_default" (기존)
      - "builtin:kr_default"
      - "csl:/path/to/style.csl"
    """
    opts = opts or FormatOptions()
    sorted_records = sort_records(records, sort_mode)

    kind, value = _parse_style_selector(style_id)

    if kind == "csl":
        # CSL 렌더링
        style_path = value or ""
        items = records_to_csl_items(sorted_records)
        return render_bibliography_text(style_path, items, locale=csl_locale, as_plain_text=True)

    # builtin 렌더링
    formatter = get_formatter(value or "kr_default")
    return formatter.format_list(sorted_records, opts)
