from __future__ import annotations

import argparse
from pathlib import Path

from core.model import ProjectSettings, Severity
from core.project import load_project, refresh_project, export_outputs, save_project_back_to_sources
from core.corrections import generate_corrections_csv, apply_corrections_csv


def cmd_run(args: argparse.Namespace) -> int:
    settings = ProjectSettings(
        style_id=args.style,
        sort_mode=args.sort,
        backup_on_save=not args.no_backup,
    )

    proj, stats = load_project(args.input, settings=settings, recursive=not args.no_recursive, include_hidden=args.include_hidden)

    # summary (콘솔)
    print("=== LOAD ===")
    print("folder      :", proj.folder)
    print("files found :", stats.files_found)
    print("files loaded:", stats.files_loaded)
    print("records     :", stats.records_loaded)
    print("parse errors:", stats.parse_errors)
    print()

    # exports
    out_dir = Path(args.output).expanduser().resolve()
    exp = export_outputs(proj, out_dir, export_references=True, export_records=True, export_issues=True)

    print("=== EXPORT ===")
    print("references.txt:", exp.references_txt)
    print("records.xlsx  :", exp.records_xlsx)
    print("issues.xlsx   :", exp.issues_xlsx)
    print()

    # errors/warns count
    flat = []
    for r in proj.records:
        flat.extend(r.issues)
    err_n = sum(1 for i in flat if i.severity == Severity.ERROR)
    warn_n = sum(1 for i in flat if i.severity == Severity.WARN)
    info_n = sum(1 for i in flat if i.severity == Severity.INFO)
    print("=== ISSUES ===")
    print("errors:", err_n, "warns:", warn_n, "infos:", info_n)
    print()

    # generate corrections template
    if args.make_corrections:
        cpath = out_dir / "corrections.csv"
        gen = generate_corrections_csv(
            proj.records,
            cpath,
            include_all_records=args.corrections_all,
            only_error_warn=not args.corrections_include_info,
        )
        print("corrections.csv:", gen)
        print("-> 엑셀로 열어서 new_value 채운 뒤, --apply-corrections로 적용하세요.")
        print()

    # apply corrections if provided
    if args.apply_corrections:
        rows, changes, errors = apply_corrections_csv(proj.records, args.apply_corrections)
        # 수정 반영 후 normalize+validate 재실행
        refresh_project(proj)

        print("=== APPLY CORRECTIONS ===")
        print("rows read :", rows)
        print("changes  :", changes)
        if errors:
            print("errors   :", len(errors))
            for e in errors[:10]:
                print(" -", e)
            if len(errors) > 10:
                print(" - ... (more)")
        print()

        # exports 다시
        exp2 = export_outputs(proj, out_dir, export_references=True, export_records=True, export_issues=True)
        print("=== RE-EXPORT AFTER CORRECTIONS ===")
        print("references.txt:", exp2.references_txt)
        print("records.xlsx  :", exp2.records_xlsx)
        print("issues.xlsx   :", exp2.issues_xlsx)
        print()

    # save back to source
    if args.save_back:
        save_stats = save_project_back_to_sources(
            proj,
            only_dirty=args.only_dirty,
            encoding=args.encoding,
        )
        print("=== SAVE BACK ===")
        print("files touched:", save_stats.files_touched)
        print("records written:", save_stats.records_written)
        print("skipped (no source_file):", save_stats.skipped_records_no_source)
        print("백업은 .bak 로 만들어집니다." if settings.backup_on_save else "백업 비활성화 상태입니다.")
        print()

    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="biblio-pipeline",
        description="RIS 폴더를 로드해서 참고문헌/이슈/정리표를 생성하고, corrections.csv로 수정 후 원본에 저장합니다."
    )
    p.add_argument("--input", required=True, help="입력 폴더 (RIS 파일들이 있는 폴더)")
    p.add_argument("--output", required=True, help="출력 폴더 (references.txt, issues.xlsx 등 생성)")
    p.add_argument("--style", default="kr_default", help="참고문헌 스타일 ID (기본: kr_default)")
    p.add_argument("--sort", default="author_year", choices=["none", "author_year", "year_author", "title"], help="정렬 방식")
    p.add_argument("--encoding", default="utf-8", help="원본 RIS 저장 시 인코딩 (기본 utf-8)")
    p.add_argument("--no-recursive", action="store_true", help="하위 폴더를 스캔하지 않음")
    p.add_argument("--include-hidden", action="store_true", help="숨김 파일/폴더도 포함")
    p.add_argument("--save-back", action="store_true", help="수정사항을 원본 RIS 파일에 저장(덮어쓰기)")
    p.add_argument("--only-dirty", action="store_true", help="dirty 레코드가 있는 파일만 저장")
    p.add_argument("--no-backup", action="store_true", help="원본 덮어쓰기 전 .bak 백업 생성 안 함 (비추)")

    # corrections options
    p.add_argument("--make-corrections", action="store_true", help="corrections.csv 템플릿 생성")
    p.add_argument("--corrections-all", action="store_true", help="(템플릿) 이슈 없는 레코드도 전부 포함")
    p.add_argument("--corrections-include-info", action="store_true", help="(템플릿) INFO 이슈도 포함")
    p.add_argument("--apply-corrections", default=None, help="corrections.csv 경로를 지정하면 적용 후 재출력")

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
