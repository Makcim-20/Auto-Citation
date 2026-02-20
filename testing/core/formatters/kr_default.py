from __future__ import annotations

import re
from typing import Optional, Sequence, List

from ..model import Record, RecordType
from .base import FormatOptions, Formatter


_SPACE_RE = re.compile(r"\s+")

# 동아시아 언어 코드 집합 (값 없음 포함 → 동아시아 서식이 기본)
_EAST_ASIAN = {"ko", "zh", "ja", "ko-kr", "zh-cn", "zh-tw", "zh-hk", "ja-jp"}


def _is_western(language: Optional[str]) -> bool:
    """language 값이 없거나 동아시아 코드면 False(동아시아 서식), 그 외 True(영미권 서식)."""
    if not language:
        return False
    return language.strip().lower() not in _EAST_ASIAN


def _clean(s: str) -> str:
    s = (s or "").replace("\u00a0", " ").strip()
    s = _SPACE_RE.sub(" ", s)
    return s


def _missing(label: str, opts: FormatOptions) -> str:
    return f"[{label}?]" if opts.show_missing_markers else ""


def _join_nonempty(parts: List[str], sep: str = " ") -> str:
    parts = [p for p in (p.strip() for p in parts) if p]
    return sep.join(parts)


# ---------------------------------------------------------------------------
# 공통 helpers
# ---------------------------------------------------------------------------

def _format_year(record: Record, opts: FormatOptions) -> str:
    if record.year is None:
        return _missing("연도", opts)
    return str(record.year)


def _format_title(record: Record, opts: FormatOptions) -> str:
    if record.title:
        return record.title.strip()
    return _missing("제목", opts)


def _format_vol_issue(record: Record) -> str:
    v = _clean(record.volume or "")
    i = _clean(record.issue or "")
    if v and i:
        return f"{v}({i})"
    if v:
        return v
    if i:
        return f"({i})"
    return ""


# ---------------------------------------------------------------------------
# 동아시아(한국어 기본) 서식
# ---------------------------------------------------------------------------

def _ea_authors(record: Record, opts: FormatOptions) -> str:
    if not record.authors:
        return _missing("저자", opts)
    names = [a.display().strip() for a in record.authors if a.display().strip()]
    if not names:
        return _missing("저자", opts)
    if opts.author_mode == "et_al_3" and len(names) >= 3:
        return f"{names[0]} 외"
    return ", ".join(names)


def _ea_container(record: Record, opts: FormatOptions) -> str:
    if record.container_title:
        return record.container_title.strip()
    if record.type == RecordType.THESIS:
        return _missing("학위수여기관/출처", opts)
    if record.type in (RecordType.BOOK, RecordType.BOOK_CHAPTER):
        return _missing("도서명/출처", opts)
    if record.type == RecordType.REPORT:
        return _missing("기관/출처", opts)
    return _missing("출처", opts)


def _ea_pages(record: Record, opts: FormatOptions) -> str:
    p = _clean(record.pages or "")
    if p:
        return p
    if record.type == RecordType.JOURNAL_ARTICLE:
        return _missing("쪽", opts)
    return ""


def _ea_doi_url(record: Record, opts: FormatOptions) -> str:
    parts: List[str] = []
    if opts.include_doi and record.doi:
        parts.append(f"doi:{record.doi}")
    if opts.include_url and record.url:
        parts.append(record.url)
    return " ".join(parts)


def _format_east_asian(record: Record, opts: FormatOptions) -> str:
    """
    동아시아(한국어) 서식:
      저자. (연도). 제목. 출처, 권(호), 쪽. doi:xxx
    """
    authors  = _ea_authors(record, opts)
    year     = _format_year(record, opts)
    title    = _format_title(record, opts)
    container = _ea_container(record, opts)
    vol_issue = _format_vol_issue(record)
    pages    = _ea_pages(record, opts)

    head = f"{authors}. ({year}). {title}."

    tail_parts: List[str] = []
    if record.type == RecordType.JOURNAL_ARTICLE:
        tail_parts.append(container)
        if vol_issue:
            tail_parts.append(vol_issue)
        if pages:
            tail_parts.append(pages)

    elif record.type == RecordType.THESIS:
        tail_parts.append(container)
        if record.institution:
            tail_parts.append(_clean(record.institution))
        if record.publisher:
            tail_parts.append(_clean(record.publisher))

    elif record.type in (RecordType.BOOK, RecordType.BOOK_CHAPTER):
        tail_parts.append(container)
        if record.publisher:
            tail_parts.append(_clean(record.publisher))
        if record.pages and record.type == RecordType.BOOK_CHAPTER:
            tail_parts.append(pages)

    elif record.type == RecordType.REPORT:
        tail_parts.append(container)
        if record.institution:
            tail_parts.append(_clean(record.institution))
        if record.publisher:
            tail_parts.append(_clean(record.publisher))

    else:
        tail_parts.append(container)
        if vol_issue:
            tail_parts.append(vol_issue)
        if pages:
            tail_parts.append(pages)

    tail = _join_nonempty(tail_parts, sep=", ")
    out = f"{head} {tail}." if tail else head

    extra = _ea_doi_url(record, opts)
    if extra:
        out = f"{out} {extra}"

    return _clean(out)


# ---------------------------------------------------------------------------
# 영미권(APA-like) 서식
# ---------------------------------------------------------------------------

def _west_authors(record: Record, opts: FormatOptions) -> str:
    if not record.authors:
        return _missing("Author", opts)
    names = [a.display().strip() for a in record.authors if a.display().strip()]
    if not names:
        return _missing("Author", opts)
    if opts.author_mode == "et_al_3" and len(names) >= 3:
        return f"{names[0]} et al."
    if len(names) == 1:
        return names[0]
    # 마지막 저자 앞에 "&"
    return ", ".join(names[:-1]) + ", & " + names[-1]


def _west_doi_url(record: Record, opts: FormatOptions) -> str:
    parts: List[str] = []
    if opts.include_doi and record.doi:
        parts.append(f"https://doi.org/{record.doi}")
    if opts.include_url and record.url:
        parts.append(record.url)
    return " ".join(parts)


def _format_western(record: Record, opts: FormatOptions) -> str:
    """
    영미권(APA-like) 서식:
      Author, A., & Author, B. (Year). Title. Container, vol(issue), pages.
      https://doi.org/xxx
    """
    authors   = _west_authors(record, opts)
    year      = _format_year(record, opts)
    title     = _format_title(record, opts)
    vol_issue = _format_vol_issue(record)

    head = f"{authors} ({year}). {title}."

    tail_parts: List[str] = []
    if record.type == RecordType.JOURNAL_ARTICLE:
        if record.container_title:
            tail_parts.append(record.container_title.strip())
        if vol_issue:
            tail_parts.append(vol_issue)
        if record.pages:
            tail_parts.append(_clean(record.pages))

    elif record.type == RecordType.THESIS:
        genre = "[Doctoral dissertation]"
        if record.institution:
            tail_parts.append(f"{genre} {_clean(record.institution)}")
        elif record.publisher:
            tail_parts.append(f"{genre} {_clean(record.publisher)}")
        else:
            tail_parts.append(genre)

    elif record.type in (RecordType.BOOK, RecordType.BOOK_CHAPTER):
        if record.type == RecordType.BOOK_CHAPTER and record.container_title:
            tail_parts.append(f"In {record.container_title.strip()}")
            if record.pages:
                tail_parts.append(f"(pp. {_clean(record.pages)})")
        if record.publisher:
            tail_parts.append(_clean(record.publisher))

    elif record.type == RecordType.REPORT:
        if record.institution:
            tail_parts.append(_clean(record.institution))
        elif record.publisher:
            tail_parts.append(_clean(record.publisher))

    else:
        if record.container_title:
            tail_parts.append(record.container_title.strip())
        if vol_issue:
            tail_parts.append(vol_issue)
        if record.pages:
            tail_parts.append(_clean(record.pages))

    tail = _join_nonempty(tail_parts, sep=", ")
    out = f"{head} {tail}." if tail else head

    extra = _west_doi_url(record, opts)
    if extra:
        out = f"{out} {extra}"

    return _clean(out)


# ---------------------------------------------------------------------------
# Formatter class
# ---------------------------------------------------------------------------

class KRDefaultFormatter:
    style_id = "kr_default"
    display_name = "국문 기본"

    def format_one(self, record: Record, opts: FormatOptions) -> str:
        if _is_western(record.language):
            return _format_western(record, opts)
        return _format_east_asian(record, opts)

    def format_list(self, records: Sequence[Record], opts: FormatOptions) -> str:
        lines = [self.format_one(r, opts) for r in records]
        return "\n".join(lines)


def get_formatter() -> Formatter:
    return KRDefaultFormatter()
