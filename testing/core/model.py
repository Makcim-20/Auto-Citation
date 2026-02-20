from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal, Tuple
import hashlib
import json
import re


# -----------------------------
# Enums / Types
# -----------------------------

class Severity(str, Enum):
    ERROR = "error"
    WARN = "warn"
    INFO = "info"


class SourceFormat(str, Enum):
    RIS = "ris"
    BIBTEX = "bibtex"
    ENDNOTE = "endnote"   # .enw 같은 거 나중에 붙일 때 대비
    UNKNOWN = "unknown"


class RecordType(str, Enum):
    # 너무 세밀하게 시작하면 바로 지옥행. MVP는 이 정도면 충분.
    JOURNAL_ARTICLE = "journalArticle"
    THESIS = "thesis"
    BOOK = "book"
    BOOK_CHAPTER = "bookChapter"
    CONFERENCE_PAPER = "conferencePaper"
    REPORT = "report"
    WEBPAGE = "webpage"
    OTHER = "other"


# -----------------------------
# Utilities
# -----------------------------

_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^0-9A-Za-z가-힣]+")


def _norm_text(s: str) -> str:
    """Stable-ish normalization for IDs and matching."""
    s = (s or "").replace("\u00a0", " ").strip()
    s = _SPACE_RE.sub(" ", s)
    s = s.lower()
    s = _PUNCT_RE.sub("", s)
    return s


def make_record_id(
    title: Optional[str],
    year: Optional[int],
    first_author: Optional[str],
    container: Optional[str],
) -> str:
    """
    Record ID must be:
      - stable across runs
      - independent of file paths
      - tolerant to minor formatting noise
    """
    key = "|".join([
        _norm_text(title or ""),
        str(year or ""),
        _norm_text(first_author or ""),
        _norm_text(container or ""),
    ])
    # 16 bytes digest -> short and stable enough for UI keys
    return hashlib.blake2b(key.encode("utf-8"), digest_size=16).hexdigest()


# -----------------------------
# Core models
# -----------------------------

@dataclass
class PersonName:
    """
    One author/editor/contributor.
    Keep both structured and literal, because real-world data is messy.
    """
    literal: str  # 원문 그대로(예: "홍길동", "Kim, Min Soo")
    family: Optional[str] = None
    given: Optional[str] = None
    # optional metadata
    role: Literal["author", "editor", "translator", "advisor", "other"] = "author"
    lang: Optional[Literal["ko", "en", "zh", "ja", "other"]] = None

    def display(self) -> str:
        # 출력용 기본: literal 우선
        if self.literal:
            return self.literal.strip()
        parts = [p for p in [self.family, self.given] if p]
        return " ".join(parts).strip()


@dataclass
class Issue:
    severity: Severity
    field: str                 # e.g. "title", "year", "authors", "journal"
    message: str               # user-facing
    record_id: Optional[str] = None
    suggestions: List[str] = field(default_factory=list)
    # For UI highlighting or later automated fixes
    code: Optional[str] = None  # e.g. "missing_required", "bad_format"


@dataclass
class Record:
    """
    A neutral, app-level bibliographic record.
    """
    id: str

    # Provenance
    source_file: Optional[str] = None          # path as string for JSON/UI (not Path)
    source_format: SourceFormat = SourceFormat.UNKNOWN
    source_record_index: Optional[int] = None  # index inside the file (0-based)

    # Type
    type: RecordType = RecordType.OTHER

    # Core bibliographic fields
    title: Optional[str] = None
    title_alt: Optional[str] = None            # 영문/한글 병기 등
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None

    authors: List[PersonName] = field(default_factory=list)

    # Container (journal/book/proceedings)
    container_title: Optional[str] = None      # journal / book / proceedings title
    container_title_alt: Optional[str] = None

    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None                # keep as string "123-130"
    publisher: Optional[str] = None
    institution: Optional[str] = None          # 학위수여기관/보고서 기관 등

    doi: Optional[str] = None
    url: Optional[str] = None

    # Extra fields (lossless)
    raw_fields: Dict[str, Any] = field(default_factory=dict)

    # State for editing workflow
    dirty: bool = False
    issues: List[Issue] = field(default_factory=list)

    def first_author_display(self) -> Optional[str]:
        return self.authors[0].display() if self.authors else None

    def container_display(self) -> Optional[str]:
        return (self.container_title or "").strip() or None

    @staticmethod
    def new(
        *,
        title: Optional[str],
        year: Optional[int],
        authors: Optional[List[PersonName]] = None,
        container_title: Optional[str] = None,
        source_file: Optional[str] = None,
        source_format: SourceFormat = SourceFormat.UNKNOWN,
        source_record_index: Optional[int] = None,
        type: RecordType = RecordType.OTHER,
        raw_fields: Optional[Dict[str, Any]] = None,
    ) -> "Record":
        authors = authors or []
        first_author = authors[0].display() if authors else None
        rid = make_record_id(title, year, first_author, container_title)
        return Record(
            id=rid,
            title=title,
            year=year,
            authors=authors,
            container_title=container_title,
            source_file=source_file,
            source_format=source_format,
            source_record_index=source_record_index,
            type=type,
            raw_fields=raw_fields or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        """JSON serializable dict for caching/projects."""
        d = asdict(self)
        # Enums to values
        d["source_format"] = self.source_format.value
        d["type"] = self.type.value
        # issues: enum handling
        for it in d.get("issues", []):
            if isinstance(it.get("severity"), Severity):
                it["severity"] = it["severity"].value
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Record":
        authors = [PersonName(**a) for a in d.get("authors", [])]
        issues = []
        for it in d.get("issues", []):
            sev = Severity(it["severity"])
            issues.append(Issue(
                severity=sev,
                field=it["field"],
                message=it["message"],
                record_id=it.get("record_id"),
                suggestions=list(it.get("suggestions", [])),
                code=it.get("code"),
            ))
        r = Record(
            id=d["id"],
            source_file=d.get("source_file"),
            source_format=SourceFormat(d.get("source_format", "unknown")),
            source_record_index=d.get("source_record_index"),
            type=RecordType(d.get("type", "other")),
            title=d.get("title"),
            title_alt=d.get("title_alt"),
            year=d.get("year"),
            month=d.get("month"),
            day=d.get("day"),
            authors=authors,
            container_title=d.get("container_title"),
            container_title_alt=d.get("container_title_alt"),
            volume=d.get("volume"),
            issue=d.get("issue"),
            pages=d.get("pages"),
            publisher=d.get("publisher"),
            institution=d.get("institution"),
            doi=d.get("doi"),
            url=d.get("url"),
            raw_fields=dict(d.get("raw_fields", {})),
            dirty=bool(d.get("dirty", False)),
            issues=issues,
        )
        return r


@dataclass
class ProjectSettings:
    """
    App-level settings that affect formatting/validation.
    """
    style_id: str = "kr_default"               # 참고문헌 형식 선택
    sort_mode: Literal["none", "author_year", "year_author", "title"] = "author_year"
    language_pref: Literal["auto", "ko", "en"] = "auto"
    # If True, always write .bak before overwriting source files
    backup_on_save: bool = True


@dataclass
class Project:
    """
    Represents a loaded folder and its records.
    """
    folder: str
    settings: ProjectSettings = field(default_factory=ProjectSettings)
    records: List[Record] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)  # global issues (file read errors etc.)

    def add_records(self, new_records: List[Record]) -> None:
        self.records.extend(new_records)

    def get_record(self, record_id: str) -> Optional[Record]:
        for r in self.records:
            if r.id == record_id:
                return r
        return None

    def dirty_records(self) -> List[Record]:
        return [r for r in self.records if r.dirty]

    def to_json(self) -> str:
        payload = {
            "folder": self.folder,
            "settings": asdict(self.settings),
            "records": [r.to_dict() for r in self.records],
            "issues": [
                {
                    "severity": i.severity.value,
                    "field": i.field,
                    "message": i.message,
                    "record_id": i.record_id,
                    "suggestions": i.suggestions,
                    "code": i.code,
                }
                for i in self.issues
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def from_json(s: str) -> "Project":
        d = json.loads(s)
        settings = ProjectSettings(**d.get("settings", {}))
        proj = Project(folder=d["folder"], settings=settings)
        proj.records = [Record.from_dict(r) for r in d.get("records", [])]
        proj.issues = [
            Issue(
                severity=Severity(i["severity"]),
                field=i["field"],
                message=i["message"],
                record_id=i.get("record_id"),
                suggestions=list(i.get("suggestions", [])),
                code=i.get("code"),
            )
            for i in d.get("issues", [])
        ]
        return proj
