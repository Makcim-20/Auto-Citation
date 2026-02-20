from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .model import Record, PersonName


_SPACE_RE = re.compile(r"\s+")
_PAGES_RANGE_RE = re.compile(r"^\s*(\d+)\s*[-–—]\s*(\d+)\s*$")
_DOI_RE = re.compile(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)


def _clean_spaces(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = s.replace("\u00a0", " ").strip()
    s = _SPACE_RE.sub(" ", s)
    return s or None


def normalize_title(s: Optional[str]) -> Optional[str]:
    s = _clean_spaces(s)
    if not s:
        return None
    # 양 끝 따옴표/괄호 같은 잡음 제거(과격하게는 하지 말자)
    s = s.strip(" '\"“”‘’")
    return s or None


def normalize_container(s: Optional[str]) -> Optional[str]:
    s = _clean_spaces(s)
    if not s:
        return None
    # 너무 길게 중복되는 괄호 정보는 일단 유지. (정책은 v1에서 더 다듬는 걸로)
    return s or None


def normalize_pages(pages: Optional[str]) -> Optional[str]:
    pages = _clean_spaces(pages)
    if not pages:
        return None

    # 대시 통일
    pages = pages.replace("–", "-").replace("—", "-")
    pages = pages.replace(" ", "")

    m = _PAGES_RANGE_RE.match(pages)
    if m:
        a, b = m.group(1), m.group(2)
        return f"{a}-{b}"
    # "pp.123-130" 같은 거 제거
    pages = re.sub(r"^(pp\.?|p\.)", "", pages, flags=re.IGNORECASE).strip()
    return pages or None


def normalize_url(url: Optional[str]) -> Optional[str]:
    url = _clean_spaces(url)
    if not url:
        return None
    # 흔한 괄호/마침표 말단 제거
    url = url.rstrip(").,;")
    return url or None


def normalize_doi(doi: Optional[str]) -> Optional[str]:
    doi = _clean_spaces(doi)
    if not doi:
        return None

    doi = doi.strip()
    doi = re.sub(r"^doi\s*:\s*", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)

    m = _DOI_RE.search(doi)
    if m:
        # DOI는 보통 소문자로 정규화(표기 일관성)
        return m.group(1).strip().lower()

    # 그래도 뭔가 들어있으면 소문자 처리만
    return doi.lower()


def normalize_author_literal(lit: str) -> str:
    lit = _clean_spaces(lit) or ""
    # "Kim , Minsoo" 같은 쉼표 주변 정리
    lit = re.sub(r"\s*,\s*", ", ", lit)
    # 중복 공백
    lit = _SPACE_RE.sub(" ", lit).strip()
    return lit


def try_split_family_given(lit: str) -> Tuple[Optional[str], Optional[str]]:
    """
    아주 보수적으로만 분해.
    - "Family, Given" 형태면 나눔
    - 그 외는 손대지 않음(한글 이름은 분해가 위험)
    """
    if "," in lit:
        parts = [p.strip() for p in lit.split(",", 1)]
        family = parts[0] or None
        given = parts[1] or None
        return family, given
    return None, None


def normalize_authors(authors: List[PersonName]) -> List[PersonName]:
    out: List[PersonName] = []
    seen = set()

    for a in authors:
        lit = normalize_author_literal(a.literal or "")
        if not lit:
            continue

        # 중복 제거(완전 동일 literal 기준)
        key = lit.lower()
        if key in seen:
            continue
        seen.add(key)

        family, given = (a.family, a.given)
        if not family and not given:
            f2, g2 = try_split_family_given(lit)
            family, given = f2, g2

        out.append(PersonName(
            literal=lit,
            family=family,
            given=given,
            role=a.role,
            lang=a.lang,
        ))

    return out


def normalize_year(y: Optional[int]) -> Optional[int]:
    if y is None:
        return None
    try:
        y = int(y)
    except Exception:
        return None
    # 범위는 validate에서 경고/오류 처리
    return y


def normalize_record(record: Record, *, mark_dirty: bool = False) -> Record:
    """
    In-place normalization (returns same object for convenience).
    """
    before = record.to_dict()  # 비교용(가벼운 수준)

    record.title = normalize_title(record.title)
    record.title_alt = normalize_title(record.title_alt)

    record.container_title = normalize_container(record.container_title)
    record.container_title_alt = normalize_container(record.container_title_alt)

    record.pages = normalize_pages(record.pages)
    record.url = normalize_url(record.url)
    record.doi = normalize_doi(record.doi)

    record.publisher = _clean_spaces(record.publisher)
    record.institution = _clean_spaces(record.institution)

    record.volume = _clean_spaces(record.volume)
    record.issue = _clean_spaces(record.issue)

    record.year = normalize_year(record.year)
    record.month = normalize_year(record.month)
    record.day = normalize_year(record.day)

    record.authors = normalize_authors(record.authors)

    # raw_fields도 최소한의 공백 정리만 (태그를 건드리진 않음)
    if record.raw_fields:
        for k, v in list(record.raw_fields.items()):
            if isinstance(v, str):
                record.raw_fields[k] = _clean_spaces(v)
            elif isinstance(v, list):
                record.raw_fields[k] = [(_clean_spaces(x) if isinstance(x, str) else x) for x in v]

    after = record.to_dict()
    if mark_dirty and before != after:
        record.dirty = True

    return record


def normalize_records(records: List[Record], *, mark_dirty: bool = False) -> List[Record]:
    for r in records:
        normalize_record(r, mark_dirty=mark_dirty)
    return records
