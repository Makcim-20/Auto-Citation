from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List

from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QMainWindow, QFileDialog, QMessageBox,
    QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QLineEdit, QTextEdit, QComboBox, QFormLayout,
    QSpinBox, QGroupBox, QApplication
)

from core.model import Project, ProjectSettings, Record, RecordType, Severity
from core.project import load_project, refresh_project, save_project_back_to_sources, export_outputs
from core.normalize import normalize_record
from core.validate import validate_record
from core.formatting import format_references

# ✅ styles registry (builtin + csl)
from core.style_registry import list_styles

# ✅ step 5: config + paths
from core.config import load_config, save_config, AppConfig
from core.paths import app_styles_dir, user_styles_dir


@dataclass
class RecordRowMeta:
    record_id: str
    errors: int
    warns: int
    title: str


def _count_issues(r: Record) -> tuple[int, int, int]:
    e = sum(1 for it in (r.issues or []) if it.severity == Severity.ERROR)
    w = sum(1 for it in (r.issues or []) if it.severity == Severity.WARN)
    i = sum(1 for it in (r.issues or []) if it.severity == Severity.INFO)
    return e, w, i


def _record_label(r: Record) -> str:
    e, w, _ = _count_issues(r)
    title = (r.title or "").strip() or "(제목 없음)"
    year = f"{r.year}" if r.year else "연도?"
    badge = f"[E{e}/W{w}]"
    return f"{badge} {title} ({year})"


def _authors_to_text(r: Record) -> str:
    if not r.authors:
        return ""
    return "; ".join(a.display() for a in r.authors if a.display().strip())


def _set_authors_from_text(r: Record, text: str) -> None:
    from core.model import PersonName
    parts = [p.strip() for p in (text or "").split(";") if p.strip()]
    r.authors = [PersonName(literal=p, role="author") for p in parts]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("서지 폴더 → 참고문헌 생성기 (MVP GUI)")

        self.project: Optional[Project] = None
        self.current_record: Optional[Record] = None

        # ✅ Step 5: config load (last style/sort)
        self.cfg: AppConfig = load_config()

        # ----- Top toolbar-ish row -----
        top = QWidget()
        top_l = QHBoxLayout(top)
        top_l.setContentsMargins(8, 8, 8, 8)

        self.btn_open = QPushButton("폴더 열기")
        self.btn_reload = QPushButton("다시 로드")

        # ✅ Step 5: refresh styles
        self.btn_refresh_styles = QPushButton("스타일 새로고침")

        self.btn_save = QPushButton("저장(원본 RIS 반영)")
        self.btn_export = QPushButton("내보내기(output)")
        self.btn_copy_all = QPushButton("전체 참고문헌 복사")

        self.style_combo = QComboBox()
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["author_year", "year_author", "title", "none"])

        top_l.addWidget(self.btn_open)
        top_l.addWidget(self.btn_reload)
        top_l.addWidget(self.btn_refresh_styles)
        top_l.addSpacing(12)
        top_l.addWidget(QLabel("스타일"))
        top_l.addWidget(self.style_combo)
        top_l.addWidget(QLabel("정렬"))
        top_l.addWidget(self.sort_combo)
        top_l.addStretch(1)
        top_l.addWidget(self.btn_copy_all)
        top_l.addWidget(self.btn_export)
        top_l.addWidget(self.btn_save)

        # ----- Main splitter -----
        splitter = QSplitter(Qt.Horizontal)

        # Left: record list
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(8, 8, 8, 8)
        self.lbl_folder = QLabel("폴더: (미선택)")
        self.lbl_stats = QLabel("레코드: 0")
        self.list_records = QListWidget()
        left_l.addWidget(self.lbl_folder)
        left_l.addWidget(self.lbl_stats)
        left_l.addWidget(self.list_records)

        # Middle: editor
        mid = QWidget()
        mid_l = QVBoxLayout(mid)
        mid_l.setContentsMargins(8, 8, 8, 8)

        editor_box = QGroupBox("레코드 편집 (WYSIWYG-ish)")
        form = QFormLayout(editor_box)

        self.type_combo = QComboBox()
        self.type_combo.addItems([t.value for t in RecordType])

        self.title_edit = QLineEdit()
        self.title_alt_edit = QLineEdit()

        self.year_spin = QSpinBox()
        self.year_spin.setRange(0, 3000)
        self.year_spin.setSpecialValueText("")

        self.authors_edit = QLineEdit()
        self.authors_edit.setPlaceholderText("세미콜론(;)으로 구분: 예) 홍길동; 김철수")

        self.container_edit = QLineEdit()
        self.volume_edit = QLineEdit()
        self.issue_edit = QLineEdit()
        self.pages_edit = QLineEdit()
        self.doi_edit = QLineEdit()
        self.url_edit = QLineEdit()
        self.publisher_edit = QLineEdit()
        self.institution_edit = QLineEdit()

        form.addRow("유형", self.type_combo)
        form.addRow("제목", self.title_edit)
        form.addRow("대체 제목", self.title_alt_edit)
        form.addRow("연도", self.year_spin)
        form.addRow("저자", self.authors_edit)
        form.addRow("출처(학술지/도서)", self.container_edit)
        form.addRow("권", self.volume_edit)
        form.addRow("호", self.issue_edit)
        form.addRow("쪽", self.pages_edit)
        form.addRow("DOI", self.doi_edit)
        form.addRow("URL", self.url_edit)
        form.addRow("출판사", self.publisher_edit)
        form.addRow("기관(학위/보고서)", self.institution_edit)

        self.issues_box = QGroupBox("이슈(누락/형식 경고)")
        issues_l = QVBoxLayout(self.issues_box)
        self.issues_view = QTextEdit()
        self.issues_view.setReadOnly(True)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.Monospace)
        self.issues_view.setFont(mono)
        issues_l.addWidget(self.issues_view)

        mid_l.addWidget(editor_box)
        mid_l.addWidget(self.issues_box)

        # Right: preview
        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(8, 8, 8, 8)

        self.preview_one_box = QGroupBox("선택 레코드 참고문헌 미리보기")
        p1_l = QVBoxLayout(self.preview_one_box)
        self.preview_one = QTextEdit()
        self.preview_one.setReadOnly(True)
        p1_l.addWidget(self.preview_one)

        self.preview_all_box = QGroupBox("전체 참고문헌 미리보기")
        p2_l = QVBoxLayout(self.preview_all_box)
        self.preview_all = QTextEdit()
        self.preview_all.setReadOnly(True)
        p2_l.addWidget(self.preview_all)

        right_l.addWidget(self.preview_one_box)
        right_l.addWidget(self.preview_all_box)

        splitter.addWidget(left)
        splitter.addWidget(mid)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 2)

        # Root layout
        root = QWidget()
        root_l = QVBoxLayout(root)
        root_l.setContentsMargins(0, 0, 0, 0)
        root_l.addWidget(top)
        root_l.addWidget(splitter)
        self.setCentralWidget(root)

        # ✅ Step 5: apply last sort first (block signals)
        with QSignalBlocker(self.sort_combo):
            idx = self.sort_combo.findText(self.cfg.last_sort)
            if idx >= 0:
                self.sort_combo.setCurrentIndex(idx)

        # Populate style list (also restores last style)
        self._reload_styles()

        # Wire signals
        self.btn_open.clicked.connect(self.on_open_folder)
        self.btn_reload.clicked.connect(self.on_reload)
        self.btn_refresh_styles.clicked.connect(self.on_refresh_styles)
        self.btn_save.clicked.connect(self.on_save_back)
        self.btn_export.clicked.connect(self.on_export)
        self.btn_copy_all.clicked.connect(self.on_copy_all)

        self.list_records.currentRowChanged.connect(self.on_select_record)
        self.style_combo.currentIndexChanged.connect(self.on_style_or_sort_changed)
        self.sort_combo.currentIndexChanged.connect(self.on_style_or_sort_changed)

        # Editor change signals
        self.type_combo.currentIndexChanged.connect(self.on_edit_changed)
        self.title_edit.textEdited.connect(self.on_edit_changed)
        self.title_alt_edit.textEdited.connect(self.on_edit_changed)
        self.year_spin.valueChanged.connect(self.on_edit_changed)
        self.authors_edit.textEdited.connect(self.on_edit_changed)
        self.container_edit.textEdited.connect(self.on_edit_changed)
        self.volume_edit.textEdited.connect(self.on_edit_changed)
        self.issue_edit.textEdited.connect(self.on_edit_changed)
        self.pages_edit.textEdited.connect(self.on_edit_changed)
        self.doi_edit.textEdited.connect(self.on_edit_changed)
        self.url_edit.textEdited.connect(self.on_edit_changed)
        self.publisher_edit.textEdited.connect(self.on_edit_changed)
        self.institution_edit.textEdited.connect(self.on_edit_changed)

        self._set_enabled(False)

    def _set_enabled(self, enabled: bool):
        self.btn_reload.setEnabled(enabled)
        self.btn_save.setEnabled(enabled)
        self.btn_export.setEnabled(enabled)
        self.btn_copy_all.setEnabled(enabled)
        self.list_records.setEnabled(enabled)

        for w in [
            self.type_combo, self.title_edit, self.title_alt_edit, self.year_spin,
            self.authors_edit, self.container_edit, self.volume_edit, self.issue_edit,
            self.pages_edit, self.doi_edit, self.url_edit, self.publisher_edit, self.institution_edit
        ]:
            w.setEnabled(enabled)

    # -----------------------------
    # Style handling (Step 5)
    # -----------------------------

    def _reload_styles(self):
        """
        builtin + (app/user) styles/*.csl 을 콤보박스에 로드.
        - config의 last_style 우선 적용
        """
        prev = self._current_style_selector() if self.style_combo.count() else None

        self.style_combo.clear()

        # style_registry가 step5 버전이면 styles_dir 인자를 안 받을 수도 있어서 안전하게 호출
        try:
            styles = list_styles(include_builtin=True, include_csl=True)  # step5
        except TypeError:
            styles = list_styles(styles_dir="styles", include_builtin=True, include_csl=True)  # legacy

        for s in styles:
            label = s.name if s.kind == "builtin" else f"{s.name} (CSL)"
            self.style_combo.addItem(label, s.to_selector_value())

        # selection priority: config > prev > default
        target = None
        if self.cfg and self.cfg.last_style:
            target = self.cfg.last_style
        elif prev:
            target = prev

        if target:
            idx = self.style_combo.findData(target)
            if idx >= 0:
                self.style_combo.setCurrentIndex(idx)
                return

        idx = self.style_combo.findData("builtin:kr_default")
        if idx >= 0:
            self.style_combo.setCurrentIndex(idx)
        elif self.style_combo.count() > 0:
            self.style_combo.setCurrentIndex(0)

    def _current_style_selector(self) -> str:
        data = self.style_combo.currentData()
        return data if isinstance(data, str) else "builtin:kr_default"

    def _current_sort_mode(self) -> str:
        return self.sort_combo.currentText()

    def _persist_ui_config(self):
        """
        현재 UI 선택값을 config에 저장.
        폴더를 안 열어도(프로젝트 없어도) 저장함.
        """
        self.cfg.last_style = self._current_style_selector()
        self.cfg.last_sort = self._current_sort_mode()
        save_config(self.cfg)

    def on_refresh_styles(self):
        """
        styles 폴더를 다시 스캔해서 콤보박스 갱신.
        """
        # 폴더 없으면 만들어줌 (사람들은 폴더 만드는 걸 싫어하니까)
        app_styles_dir().mkdir(parents=True, exist_ok=True)
        user_styles_dir().mkdir(parents=True, exist_ok=True)

        self._reload_styles()
        self._persist_ui_config()

        # 프로젝트가 있으면 즉시 반영
        if self.project:
            self.project.settings.style_id = self._current_style_selector()
            self.project.settings.sort_mode = self._current_sort_mode()  # type: ignore
            self._refresh_all_preview()
            self._refresh_one_preview()

        QMessageBox.information(
            self,
            "스타일 갱신",
            "CSL 스타일을 폴더에 넣고 다시 누르면 목록이 갱신됩니다.\n\n"
            f"- 앱 styles: {app_styles_dir()}\n"
            f"- 사용자 styles: {user_styles_dir()}"
        )

    # -----------------------------
    # Folder load / project
    # -----------------------------

    def on_open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "RIS 폴더 선택")
        if not folder:
            return
        self._load_folder(folder)

    def on_reload(self):
        if not self.project:
            return
        self._load_folder(self.project.folder)

    def _load_folder(self, folder: str):
        try:
            settings = ProjectSettings(
                style_id=self._current_style_selector(),
                sort_mode=self._current_sort_mode(),  # type: ignore
                backup_on_save=True,
            )
            proj, stats = load_project(folder, settings=settings)
            self.project = proj
            self.current_record = None

            self.lbl_folder.setText(f"폴더: {proj.folder}")
            self.lbl_stats.setText(
                f"레코드: {len(proj.records)} | 파일: {stats.files_loaded}/{stats.files_found} | 파싱오류: {stats.parse_errors}"
            )

            self._rebuild_record_list()
            self._set_enabled(True)
            self._refresh_all_preview()

            if len(proj.records) > 0:
                self.list_records.setCurrentRow(0)

        except Exception as e:
            QMessageBox.critical(self, "로드 실패", f"{type(e).__name__}: {e}")

    def _rebuild_record_list(self):
        self.list_records.clear()
        if not self.project:
            return

        for r in self.project.records:
            item = QListWidgetItem(_record_label(r))
            e, _, _ = _count_issues(r)
            if e > 0:
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            self.list_records.addItem(item)

    def on_select_record(self, row: int):
        if not self.project or row < 0 or row >= len(self.project.records):
            self.current_record = None
            return

        r = self.project.records[row]
        self.current_record = r
        self._load_record_into_editor(r)
        self._refresh_one_preview()
        self._refresh_issues_view(r)

    def _load_record_into_editor(self, r: Record):
        blockers = [
            QSignalBlocker(self.type_combo),
            QSignalBlocker(self.title_edit),
            QSignalBlocker(self.title_alt_edit),
            QSignalBlocker(self.year_spin),
            QSignalBlocker(self.authors_edit),
            QSignalBlocker(self.container_edit),
            QSignalBlocker(self.volume_edit),
            QSignalBlocker(self.issue_edit),
            QSignalBlocker(self.pages_edit),
            QSignalBlocker(self.doi_edit),
            QSignalBlocker(self.url_edit),
            QSignalBlocker(self.publisher_edit),
            QSignalBlocker(self.institution_edit),
        ]
        try:
            idx = self.type_combo.findText(r.type.value)
            if idx >= 0:
                self.type_combo.setCurrentIndex(idx)

            self.title_edit.setText(r.title or "")
            self.title_alt_edit.setText(r.title_alt or "")
            self.year_spin.setValue(int(r.year) if isinstance(r.year, int) else 0)
            self.authors_edit.setText(_authors_to_text(r))
            self.container_edit.setText(r.container_title or "")
            self.volume_edit.setText(r.volume or "")
            self.issue_edit.setText(r.issue or "")
            self.pages_edit.setText(r.pages or "")
            self.doi_edit.setText(r.doi or "")
            self.url_edit.setText(r.url or "")
            self.publisher_edit.setText(r.publisher or "")
            self.institution_edit.setText(r.institution or "")
        finally:
            _ = blockers

    def on_edit_changed(self):
        if not self.project or not self.current_record:
            return

        r = self.current_record

        try:
            tval = self.type_combo.currentText()
            try:
                r.type = RecordType(tval)
            except Exception:
                r.type = RecordType.OTHER

            r.title = self.title_edit.text().strip() or None
            r.title_alt = self.title_alt_edit.text().strip() or None

            y = self.year_spin.value()
            r.year = None if y == 0 else int(y)

            _set_authors_from_text(r, self.authors_edit.text())

            r.container_title = self.container_edit.text().strip() or None
            r.volume = self.volume_edit.text().strip() or None
            r.issue = self.issue_edit.text().strip() or None
            r.pages = self.pages_edit.text().strip() or None
            r.doi = self.doi_edit.text().strip() or None
            r.url = self.url_edit.text().strip() or None
            r.publisher = self.publisher_edit.text().strip() or None
            r.institution = self.institution_edit.text().strip() or None

            normalize_record(r, mark_dirty=False)
            validate_record(r)
            r.dirty = True

            idx = self.list_records.currentRow()
            if idx >= 0:
                self.list_records.item(idx).setText(_record_label(r))

            self._refresh_one_preview()
            self._refresh_all_preview()
            self._refresh_issues_view(r)

        except Exception as e:
            QMessageBox.warning(self, "편집 반영 실패", f"{type(e).__name__}: {e}")

    def on_style_or_sort_changed(self):
        """
        스타일/정렬 변경:
        - config에 저장
        - 프로젝트 있으면 설정 반영 + 미리보기 갱신
        """
        self._persist_ui_config()

        if self.project:
            self.project.settings.style_id = self._current_style_selector()
            self.project.settings.sort_mode = self._current_sort_mode()  # type: ignore
            self._refresh_all_preview()
            self._refresh_one_preview()

    def _refresh_issues_view(self, r: Record):
        lines: List[str] = []
        for it in (r.issues or []):
            lines.append(f"[{it.severity.value.upper():5}] {it.field}: {it.message}")
        if not lines:
            lines = ["(이슈 없음)"]
        self.issues_view.setPlainText("\n".join(lines))

    def _refresh_one_preview(self):
        if not self.project or not self.current_record:
            self.preview_one.setPlainText("")
            return

        txt = format_references(
            [self.current_record],
            style_id=self._current_style_selector(),
            sort_mode="none",
        )
        self.preview_one.setPlainText(txt)

    def _refresh_all_preview(self):
        if not self.project:
            self.preview_all.setPlainText("")
            return

        txt = format_references(
            self.project.records,
            style_id=self._current_style_selector(),
            sort_mode=self._current_sort_mode(),
        )
        self.preview_all.setPlainText(txt)

    def on_copy_all(self):
        if not self.project:
            return
        txt = self.preview_all.toPlainText()
        QApplication.clipboard().setText(txt)
        QMessageBox.information(self, "복사 완료", "전체 참고문헌이 클립보드에 복사되었습니다.")

    def on_export(self):
        if not self.project:
            return
        out_dir = QFileDialog.getExistingDirectory(self, "output 폴더 선택")
        if not out_dir:
            return
        try:
            refresh_project(self.project)

            # export도 selector 그대로 (formatting.py가 builtin/csl 분기 처리)
            self.project.settings.style_id = self._current_style_selector()
            self.project.settings.sort_mode = self._current_sort_mode()  # type: ignore

            exp = export_outputs(self.project, out_dir, export_references=True, export_records=True, export_issues=True)
            QMessageBox.information(
                self,
                "내보내기 완료",
                f"references.txt / records.xlsx / issues.xlsx 생성 완료\n\n{exp}"
            )
        except Exception as e:
            QMessageBox.critical(self, "내보내기 실패", f"{type(e).__name__}: {e}")

    def on_save_back(self):
        if not self.project:
            return

        reply = QMessageBox.question(
            self,
            "원본 저장",
            "수정사항을 원본 RIS 파일에 저장합니다.\n(자동으로 .bak 백업을 만듭니다)\n\n계속할까요?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            refresh_project(self.project)
            stats = save_project_back_to_sources(self.project, only_dirty=True, encoding="utf-8")
            QMessageBox.information(
                self,
                "저장 완료",
                f"파일 반영 완료\n\nfiles_touched={stats.files_touched}\nrecords_written={stats.records_written}"
            )
            self._rebuild_record_list()
        except Exception as e:
            QMessageBox.critical(self, "저장 실패", f"{type(e).__name__}: {e}")
