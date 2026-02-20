from __future__ import annotations

import re
from typing import Sequence, List

from ..model import Record, RecordType
from .base import FormatOptions, Formatter


_SPACE_RE = re.compile(r"\s+")


def _clean(s: str) -> str:
    s = (s or "").replace("\u00a0", " ").strip()
    s = _SPACE_RE.sub(" ", s)
    return s


def _missing(label: str, opts: FormatOptions) -> str:
    return f"[{label}?]" if opts.show_missing_markers else ""


def _join_nonempty(parts: List[str], sep: str = " ") -> str:
    parts = [p for p in (p.strip() for p in parts) if p]
    return sep.join(parts)


def _format_authors(record: Record, opts: FormatOptions) -> str:
    if not record.authors:
        return _missing("저자", opts)

    names = [a.display().strip() for a in record.authors if a.display().strip()]
    if not names:
        return _missing("저자", opts)

    if opts.author_mode == "et_al_3" and len(names) >= 3:
        return f"{names[0]} 외"

    # 국문에서 구분점은 정책이 다양한데, MVP는 쉼표로 통일
    return ", ".join(names)


def _format_year(record: Record, opts: FormatOptions) -> str:
    if record.year is None:
        return _missing("연도", opts)
    return str(record.year)


def _format_title(record: Record, opts: FormatOptions) -> str:
    if record.title:
        return record.title.strip()
    return _missing("제목", opts)


def _format_container(record: Record, opts: FormatOptions) -> str:
    if record.container_title:
        return record.container_title.strip()
    # 유형에 따라 label 다르게
    if record.type == RecordType.THESIS:
        return _missing("학위수여기관/출처", opts)
    if record.type in (RecordType.BOOK, RecordType.BOOK_CHAPTER):
        return _missing("도서명/출처", opts)
    if record.type == RecordType.REPORT:
        return _missing("기관/출처", opts)
    return _missing("출처", opts)


def _format_vol_issue(record: Record) -> str:
    v = _clean(record.volume or "")
    i = _clean(record.issue or "")
    if v and i:
        return f"{v}({i})"
    if v:
        return v
    if i:
        # 권 없고 호만 있으면 어색하지만 일단 표기
        return f"({i})"
    return ""


def _format_pages(record: Record, opts: FormatOptions) -> str:
    p = _clean(record.pages or "")
    if p:
        return p
    # 논문류면 pages는 권장이라 마커를 보여주는 게 좋음
    if record.type == RecordType.JOURNAL_ARTICLE:
        return _missing("쪽", opts)
    return ""


def _format_doi_url(record: Record, opts: FormatOptions) -> str:
    parts: List[str] = []
    if opts.include_doi and record.doi:
        parts.append(f"doi:{record.doi}")
    if opts.include_url and record.url:
        parts.append(record.url)
    return " ".join(parts)


class KRDefaultFormatter:
    style_id = "kr_default"
    display_name = "국문 기본"

    def format_one(self, record: Record, opts: FormatOptions) -> str:
        """
        기본 출력 형태(너무 야심차게 안 감):
          저자. (연도). 제목. 출처, 권(호), 쪽. doi:... (옵션)
        유형별로 약간씩만 다르게.
        """
        authors = _format_authors(record, opts)
        year = _format_year(record, opts)
        title = _format_title(record, opts)
        container = _format_container(record, opts)
        vol_issue = _format_vol_issue(record)
        pages = _format_pages(record, opts)

        # 공통 앞부분
        head = f"{authors}. ({year}). {title}."

        # 유형별 뒤부분
        tail_parts: List[str] = []

        if record.type == RecordType.JOURNAL_ARTICLE:
            # 출처(학술지명), 권(호), 쪽
            tail_parts.append(container)
            if vol_issue:
                tail_parts.append(vol_issue)
            if pages:
                # 한국 규정은 pp. 쓰기도 하고 생략하기도. MVP는 그냥 숫자만.
                tail_parts.append(pages)

        elif record.type == RecordType.THESIS:
            # 학위논문: (학위종류는 RIS에 없을 수도) 기관/출처 중심
            tail_parts.append(container)
            # 가능하면 institution/publisher 보강
            if record.institution:
                tail_parts.append(_clean(record.institution))
            if record.publisher:
                tail_parts.append(_clean(record.publisher))

        elif record.type in (RecordType.BOOK, RecordType.BOOK_CHAPTER):
            # 단행본/챕터: 출판사 중심
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
            # 기타: 최소 정보만
            tail_parts.append(container)
            if vol_issue:
                tail_parts.append(vol_issue)
            if pages:
                tail_parts.append(pages)

        tail = _join_nonempty(tail_parts, sep=", ")
        out = f"{head} {tail}." if tail else head

        extra = _format_doi_url(record, opts)
        if extra:
            out = f"{out} {extra}"

        return _clean(out)

    def format_list(self, records: Sequence[Record], opts: FormatOptions) -> str:
        lines = [self.format_one(r, opts) for r in records]
        return "\n".join(lines)


def get_formatter() -> Formatter:
    return KRDefaultFormatter()
