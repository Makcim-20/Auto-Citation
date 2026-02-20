from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ..model import Record, RecordType, PersonName


# --- RecordType -> CSL type mapping ---
# CSL type reference (common ones):
# article-journal, book, chapter, paper-conference, thesis, report, webpage, article
RECORDTYPE_TO_CSL_TYPE: Dict[RecordType, str] = {
    RecordType.JOURNAL_ARTICLE: "article-journal",
    RecordType.BOOK: "book",
    RecordType.BOOK_CHAPTER: "chapter",
    RecordType.CONFERENCE_PAPER: "paper-conference",
    RecordType.THESIS: "thesis",
    RecordType.REPORT: "report",
    RecordType.WEBPAGE: "webpage",
    RecordType.OTHER: "article",
}


def _int_or_none(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        if isinstance(x, bool):
            return None
        return int(x)
    except Exception:
        return None


def _strip_or_none(s: Any) -> Optional[str]:
    if s is None:
        return None
    s = str(s).strip()
    return s or None


def _date_parts(record: Record) -> Optional[Dict[str, Any]]:
    """
    CSL-JSON issued format:
      "issued": { "date-parts": [[YYYY, MM, DD]] }
    month/day는 선택.
    """
    y = _int_or_none(record.year)
    if not y:
        return None

    m = _int_or_none(getattr(record, "month", None))
    d = _int_or_none(getattr(record, "day", None))

    parts: List[int] = [y]
    if m and 1 <= m <= 12:
        parts.append(m)
        if d and 1 <= d <= 31:
            parts.append(d)

    return {"date-parts": [parts]}


def _csl_name(person: PersonName) -> Optional[Dict[str, Any]]:
    """
    CSL name object:
      - 구조화 가능하면 {"family":..., "given":...}
      - 아니면 {"literal":...}
    """
    family = _strip_or_none(person.family)
    given = _strip_or_none(person.given)
    literal = _strip_or_none(person.literal)

    # 구조화 이름 우선
    if family or given:
        out: Dict[str, Any] = {}
        if family:
            out["family"] = family
        if given:
            out["given"] = given
        # lang 같은 건 필요해지면 확장
        return out

    if literal:
        return {"literal": literal}

    return None


def _authors(record: Record) -> Optional[List[Dict[str, Any]]]:
    if not record.authors:
        return None
    out: List[Dict[str, Any]] = []
    for a in record.authors:
        obj = _csl_name(a)
        if obj:
            out.append(obj)
    return out or None


def record_to_csl_item(record: Record) -> Dict[str, Any]:
    """
    Convert our Record -> CSL-JSON item dict.

    최소 필드:
      id, type, title, author, issued, container-title, volume, issue, page, DOI, URL ...
    """
    item: Dict[str, Any] = {}

    # Required-ish
    item["id"] = record.id
    item["type"] = RECORDTYPE_TO_CSL_TYPE.get(record.type, "article")

    title = _strip_or_none(record.title)
    if title:
        item["title"] = title

    # Optional extra title (CSL has "title-short" but 의미가 다를 수 있어 alt는 넣지 않음)
    # 필요하면: item["title-short"] = record.title_alt

    auth = _authors(record)
    if auth:
        item["author"] = auth

    issued = _date_parts(record)
    if issued:
        item["issued"] = issued

    # Container (journal/book title)
    container = _strip_or_none(record.container_title)
    if container:
        item["container-title"] = container

    # Volume / Issue / Pages
    vol = _strip_or_none(record.volume)
    if vol:
        item["volume"] = vol

    iss = _strip_or_none(record.issue)
    if iss:
        item["issue"] = iss

    pages = _strip_or_none(record.pages)
    if pages:
        item["page"] = pages

    # Identifiers
    doi = _strip_or_none(record.doi)
    if doi:
        item["DOI"] = doi

    url = _strip_or_none(record.url)
    if url:
        item["URL"] = url

    # Publisher / Institution
    publisher = _strip_or_none(record.publisher)
    if publisher:
        item["publisher"] = publisher

    institution = _strip_or_none(record.institution)
    if institution:
        # CSL-JSON에는 institution이 있음 (특히 report/thesis에서 유용)
        item["institution"] = institution

        # 현실적으로 많은 스타일이 thesis에서 publisher를 쓰는 경우도 있어서 보강(선택)
        # publisher가 비어 있으면 institution을 publisher로도 넣어줌
        if "publisher" not in item:
            item["publisher"] = institution

    language = _strip_or_none(getattr(record, "language", None))
    if language:
        item["language"] = language

    # Type-specific helpful fields (필요할 때 확장)
    # paper-conference: event-title, event-place, publisher-place 등
    # thesis: genre ("Master's thesis" 등), archive 등
    # report: genre, number 등

    return item


def records_to_csl_items(records: Sequence[Record]) -> List[Dict[str, Any]]:
    return [record_to_csl_item(r) for r in records]
