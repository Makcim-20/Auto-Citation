from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .model import Project, ProjectSettings, Record, Issue, Severity
from .scan import scan_folder
from .ris import parse_ris, write_ris
from .normalize import normalize_records
from .validate import validate_records
from .formatting import format_references
from .exporters import export_references_txt, export_records_xlsx, export_issues_xlsx


@dataclass
class LoadStats:
    files_found: int
    files_loaded: int
    records_loaded: int
    parse_errors: int


def _group_records_by_source_file(records: List[Record]) -> Dict[str, List[Record]]:
    grouped: Dict[str, List[Record]] = {}
    for r in records:
        if not r.source_file:
            # 파일 출처가 없는 레코드는 저장 대상에서 제외(이슈로만 남김)
            continue
        grouped.setdefault(r.source_file, []).append(r)
    return grouped


def load_project(
    folder: str | Path,
    *,
    settings: Optional[ProjectSettings] = None,
    recursive: bool = True,
    include_hidden: bool = False,
) -> Tuple[Project, LoadStats]:
    """
    Folder -> scan .ris -> parse -> normalize -> validate
    Returns (Project, LoadStats)
    """
    root = Path(folder).expanduser().resolve()
    proj = Project(folder=str(root), settings=settings or ProjectSettings())

    paths = scan_folder(root, exts=[".ris"], recursive=recursive, include_hidden=include_hidden)
    stats = LoadStats(files_found=len(paths), files_loaded=0, records_loaded=0, parse_errors=0)

    for p in paths:
        try:
            recs, enc = parse_ris(p)
            # parse_ris sets source_file for each record already
            proj.records.extend(recs)
            stats.files_loaded += 1
            stats.records_loaded += len(recs)
        except Exception as e:
            stats.parse_errors += 1
            proj.issues.append(Issue(
                severity=Severity.ERROR,
                field="file",
                message=f"파일 파싱 실패: {p.name} ({type(e).__name__}: {e})",
                record_id=None,
                code="file_parse_error",
            ))

    # Normalize + Validate
    normalize_records(proj.records, mark_dirty=False)
    validate_records(proj.records)  # fills record.issues and returns flat list (not needed here)

    return proj, stats


def refresh_project(proj: Project) -> None:
    """
    Re-run normalize + validate (use after bulk edits).
    """
    normalize_records(proj.records, mark_dirty=False)
    validate_records(proj.records)


@dataclass
class SaveStats:
    files_touched: int
    records_written: int
    skipped_records_no_source: int


def save_project_back_to_sources(
    proj: Project,
    *,
    only_dirty: bool = False,
    encoding: str = "utf-8",
) -> SaveStats:
    """
    Writes project records back to their source .ris files.
    Strategy: file-level rewrite (safe, simple).
    If only_dirty=True, it will still rewrite the file if ANY record in that file is dirty.
    Always respects proj.settings.backup_on_save.
    """
    grouped = _group_records_by_source_file(proj.records)

    files_touched = 0
    records_written = 0
    skipped_no_source = sum(1 for r in proj.records if not r.source_file)

    for src, recs in grouped.items():
        src_path = Path(src)

        if only_dirty and not any(r.dirty for r in recs):
            continue

        # Write RIS (with .bak if enabled)
        write_ris(
            src_path,
            recs,
            backup=proj.settings.backup_on_save,
            encoding=encoding,
        )

        files_touched += 1
        records_written += len(recs)

        # Reset dirty flags (we persisted them)
        for r in recs:
            r.dirty = False

    return SaveStats(
        files_touched=files_touched,
        records_written=records_written,
        skipped_records_no_source=skipped_no_source,
    )


@dataclass
class ExportStats:
    references_txt: Optional[str]
    records_xlsx: Optional[str]
    issues_xlsx: Optional[str]


def export_outputs(
    proj: Project,
    out_dir: str | Path,
    *,
    export_references: bool = True,
    export_records: bool = True,
    export_issues: bool = True,
) -> ExportStats:
    """
    Creates output files in out_dir:
      - references.txt
      - records.xlsx
      - issues.xlsx
    """
    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    references_path = None
    records_path = None
    issues_path = None

    if export_references:
        txt = format_references(
            proj.records,
            style_id=proj.settings.style_id,
            sort_mode=proj.settings.sort_mode,
        )
        references_path = str(out / "references.txt")
        export_references_txt(txt, references_path)

    if export_records:
        records_path = str(out / "records.xlsx")
        export_records_xlsx(proj.records, records_path)

    if export_issues:
        issues_path = str(out / "issues.xlsx")
        export_issues_xlsx(proj.records, proj.issues, issues_path)

    return ExportStats(
        references_txt=references_path,
        records_xlsx=records_path,
        issues_xlsx=issues_path,
    )
