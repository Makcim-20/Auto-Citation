from __future__ import annotations

import re
from typing import List, Optional, Set

from .model import Issue, Record, Severity, RecordType


_DOI_FULL_RE = re.compile(r"^10\.\d{4,9}/[-._;()/:a-z0-9]+$", re.IGNORECASE)
_PAGES_OK_RE = re.compile(r"^\d+(-\d+)?$")  # "123" or "123-130"
_YEAR_MIN = 1900
_YEAR_MAX = 2099


def _add(issues: List[Issue], severity: Severity, field: str, message: str, record_id: Optional[str], code: str, suggestions=None):
    issues.append(Issue(
        severity=severity,
        field=field,
        message=message,
        record_id=record_id,
        code=code,
        suggestions=list(suggestions or []),
    ))


def validate_record(record: Record) -> List[Issue]:
    """
    Returns issues for a record. Also updates record.issues.
    """
    issues: List[Issue] = []
    rid = record.id

    # --- Required fields (baseline) ---
    if not record.title:
        _add(issues, Severity.ERROR, "title", "제목이 비어 있습니다.", rid, "missing_required")

    if not record.authors or all(not a.display().strip() for a in record.authors):
        _add(issues, Severity.ERROR, "authors", "저자 정보가 비어 있습니다.", rid, "missing_required")

    if record.year is None:
        _add(issues, Severity.WARN, "year", "연도 정보가 없습니다. (가능하면 입력 권장)", rid, "missing_recommended")
    else:
        if not (_YEAR_MIN <= record.year <= _YEAR_MAX):
            _add(issues, Severity.ERROR, "year", f"연도가 비정상 범위입니다: {record.year}", rid, "bad_value")

    # --- Type-specific requirements ---
    if record.type == RecordType.JOURNAL_ARTICLE:
        if not record.container_title:
            _add(issues, Severity.ERROR, "container_title", "학술지명이 비어 있습니다.", rid, "missing_required")
        if not record.volume and not record.issue:
            _add(issues, Severity.WARN, "volume/issue", "권/호 정보가 없습니다. (있으면 정확도가 크게 올라갑니다)", rid, "missing_recommended")
        if not record.pages:
            _add(issues, Severity.WARN, "pages", "페이지 정보가 없습니다. (있으면 권장)", rid, "missing_recommended")

    elif record.type == RecordType.THESIS:
        if not record.institution:
            _add(issues, Severity.WARN, "institution", "학위수여기관(대학/기관) 정보가 없습니다.", rid, "missing_recommended")

    elif record.type in (RecordType.BOOK, RecordType.BOOK_CHAPTER):
        if not record.publisher:
            _add(issues, Severity.WARN, "publisher", "출판사 정보가 없습니다.", rid, "missing_recommended")

    # --- Format sanity checks ---
    # DOI
    if record.doi:
        if not _DOI_FULL_RE.match(record.doi.strip()):
            _add(issues, Severity.WARN, "doi", f"DOI 형식이 애매합니다: {record.doi}", rid, "bad_format")

    # URL
    if record.url:
        if not (record.url.startswith("http://") or record.url.startswith("https://")):
            _add(issues, Severity.WARN, "url", f"URL이 http(s)로 시작하지 않습니다: {record.url}", rid, "bad_format")

    # pages
    if record.pages:
        p = record.pages.strip().replace("–", "-").replace("—", "-")
        p = p.replace(" ", "")
        if not _PAGES_OK_RE.match(p):
            _add(issues, Severity.WARN, "pages", f"페이지 형식이 애매합니다: {record.pages}", rid, "bad_format")

    # author weirdness
    for a in record.authors:
        lit = a.display()
        if any(ch.isdigit() for ch in lit):
            _add(issues, Severity.WARN, "authors", f"저자명에 숫자가 포함되어 있습니다(파싱 오류 가능): {lit}", rid, "suspicious")
            break

    # container suspicious swap (발행기관/학술지 뒤섞임 방지용 힌트)
    if record.container_title:
        ct = record.container_title
        if ("대학교" in ct or "학회" in ct or "연구소" in ct) and record.type == RecordType.JOURNAL_ARTICLE:
            # 학술지명에 기관명 느낌이 강하면 경고(확정은 못 하니까 WARN)
            _add(issues, Severity.INFO, "container_title",
                 f"학술지명이 기관명처럼 보입니다(필드가 뒤바뀌었을 수 있음): {ct}",
                 rid, "suspicious")

    record.issues = issues
    return issues


def validate_records(records: List[Record]) -> List[Issue]:
    """
    Validate all records and return flattened issues list.
    """
    all_issues: List[Issue] = []
    for r in records:
        all_issues.extend(validate_record(r))
    return all_issues


def filter_issues_for_fields(issues: List[Issue], relevant_fields: Set[str]) -> List[Issue]:
    """
    Return only issues whose field is relevant to the given editor field set.

    validate.py가 "volume/issue"처럼 복합 필드명을 쓰는 경우를 처리:
    relevant_fields에 "volume" 또는 "issue" 중 하나라도 있으면 포함.
    """
    result: List[Issue] = []
    for issue in issues:
        f = issue.field
        if f == "volume/issue":
            if "volume" in relevant_fields or "issue" in relevant_fields:
                result.append(issue)
        elif f in relevant_fields:
            result.append(issue)
    return result
