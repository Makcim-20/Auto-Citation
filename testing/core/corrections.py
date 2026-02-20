from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .model import Record, PersonName, RecordType


# 우리가 corrections로 다룰 "수정 가능한 필드" 목록
EDITABLE_FIELDS = [
    "type",
    "title",
    "title_alt",
    "year",
    "authors",  # semicolon separated
    "container_title",
    "container_title_alt",
    "volume",
    "issue",
    "pages",
    "doi",
    "url",
    "publisher",
    "institution",
]


def _safe_str(v) -> str:
    return "" if v is None else str(v)


def _authors_to_str(record: Record) -> str:
    if not record.authors:
        return ""
    return "; ".join(a.display() for a in record.authors if a.display().strip())


def _get_field_value(record: Record, field: str) -> str:
    if field == "authors":
        return _authors_to_str(record)
    if field == "type":
        return record.type.value
    return _safe_str(getattr(record, field, ""))


def _set_field_value(record: Record, field: str, new_value: str) -> bool:
    """
    Apply correction. Returns True if record changed.
    """
    new_value = (new_value or "").strip()

    if field == "authors":
        # "홍길동; 김철수" 형태
        if not new_value:
            # authors를 비우는 건 위험하지만 허용은 함(나중에 validate가 잡아줌)
            if record.authors:
                record.authors = []
                return True
            return False

        parts = [p.strip() for p in new_value.split(";") if p.strip()]
        new_authors = [PersonName(literal=p, role="author") for p in parts]
        old = _authors_to_str(record)
        if old != new_value:
            record.authors = new_authors
            return True
        return False

    if field == "year":
        if not new_value:
            if record.year is not None:
                record.year = None
                return True
            return False
        try:
            y = int(new_value)
        except ValueError:
            # 숫자가 아니면 적용하지 않음
            return False
        if record.year != y:
            record.year = y
            return True
        return False

    if field == "type":
        if not new_value:
            return False
        # RecordType value로 매핑
        try:
            rt = RecordType(new_value)
        except Exception:
            # 대소문자/별칭 대응은 v1에서
            return False
        if record.type != rt:
            record.type = rt
            return True
        return False

    # 일반 문자열 필드
    old = _safe_str(getattr(record, field, "") or "")
    if (old or "").strip() != new_value:
        setattr(record, field, new_value or None)
        return True
    return False


def generate_corrections_csv(
    records: Sequence[Record],
    path: str | Path,
    *,
    include_all_records: bool = False,
    only_error_warn: bool = True,
) -> str:
    """
    Create a corrections.csv template.

    - include_all_records=False: 이슈가 있는 레코드만 포함
    - only_error_warn=True: INFO는 제외하고 ERROR/WARN만 대상으로
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    # 어떤 레코드를 포함할지 결정
    selected: List[Record] = []
    for r in records:
        if include_all_records:
            selected.append(r)
            continue
        if not r.issues:
            continue
        if only_error_warn:
            if any(it.severity.value in ("error", "warn") for it in r.issues):
                selected.append(r)
        else:
            selected.append(r)

    # corrections CSV는 레코드-필드 단위로 한 줄씩 만드는 게 제일 편함
    # (엑셀에서 필드별로 고치기 쉬움)
    rows: List[Dict[str, str]] = []

    for r in selected:
        issue_fields = {it.field for it in (r.issues or [])}
        # issue_fields가 "volume/issue" 같이 합쳐져 있을 수 있으니, 매핑 완벽하진 않음.
        # MVP는 "있으면 해당/비슷한 필드 위주로" 많이 뿌려준다.

        # 최소 수정 대상 필드 세트: 필수/자주 틀리는 것 + 이슈 관련
        candidate_fields = ["type", "title", "authors", "year", "container_title", "volume", "issue", "pages", "doi", "url", "publisher", "institution"]

        for f in candidate_fields:
            # include_all_records=False라면 이슈 관련 필드 위주로 줄이자
            if not include_all_records:
                if f not in issue_fields and f not in ("type", "title", "authors", "year", "container_title"):
                    # 핵심 필드는 항상 보여주고, 나머지는 이슈가 있을 때만
                    continue

            rows.append({
                "record_id": r.id,
                "source_file": r.source_file or "",
                "field": f,
                "current_value": _get_field_value(r, f),
                "new_value": "",
                "note": "수정할 값이 있으면 new_value에 입력하세요. 비우면 그대로 둡니다.",
                "title_hint": (r.title or ""),
            })

    with p.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["record_id", "source_file", "field", "current_value", "new_value", "note", "title_hint"])
        w.writeheader()
        w.writerows(rows)

    return str(p)


def apply_corrections_csv(
    records: List[Record],
    path: str | Path,
) -> Tuple[int, int, List[str]]:
    """
    Apply corrections from corrections.csv to records.

    Returns (rows_read, changes_applied, errors)
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Corrections file not found: {p}")

    rec_map: Dict[str, Record] = {r.id: r for r in records}

    rows_read = 0
    changes = 0
    errors: List[str] = []

    with p.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows_read += 1
            rid = (row.get("record_id") or "").strip()
            field = (row.get("field") or "").strip()
            new_value = (row.get("new_value") or "").strip()

            if not rid or rid not in rec_map:
                # record_id가 깨졌거나, 로드된 데이터와 매칭이 안 되는 경우
                errors.append(f"Row {rows_read}: record_id not found: {rid}")
                continue

            if field not in EDITABLE_FIELDS:
                errors.append(f"Row {rows_read}: unsupported field: {field}")
                continue

            if new_value == "":
                # 빈 값은 '변경 없음' 취급
                continue

            r = rec_map[rid]
            try:
                changed = _set_field_value(r, field, new_value)
                if changed:
                    r.dirty = True
                    changes += 1
            except Exception as e:
                errors.append(f"Row {rows_read}: failed to apply ({rid}, {field}): {type(e).__name__}: {e}")

    return rows_read, changes, errors
