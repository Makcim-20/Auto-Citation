from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, List, Dict

from PySide6.QtCore import Qt, QSignalBlocker, QTimer
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QMainWindow, QFileDialog, QMessageBox,
    QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QLineEdit, QTextEdit, QComboBox, QFormLayout,
    QSpinBox, QGroupBox, QApplication
)

from core.model import Project, ProjectSettings, Record, RecordType, Severity
from core.project import load_project, refresh_project, save_project_back_to_sources, export_outputs
from core.normalize import normalize_record
from core.validate import validate_record, filter_issues_for_fields
from core.formatting import format_references

# styles registry (builtin + csl + type fields)
from core.style_registry import list_styles, editor_fields_for_csl, fields_for_type

# config
from core.config import load_config, save_config, AppConfig

_UNDO_DEBOUNCE = 0.8   # 초: 이 시간 내 연속 입력은 하나의 undo 단계로 묶임
_MAX_UNDO_DEPTH = 50   # 레코드당 최대 undo 스텝 수
_AUTOSAVE_DELAY_MS = 2000  # 자동저장 딜레이(ms)


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

        # config load (last style/sort/csl_folder)
        self.cfg: AppConfig = load_config()

        # undo/redo: record.id → list of Record.to_dict() snapshots
        self._undo_stacks: Dict[str, List[Dict]] = {}
        self._redo_stacks: Dict[str, List[Dict]] = {}
        self._last_undo_push: Dict[str, float] = {}  # record.id → monotonic timestamp

        # 자동저장 타이머 (마지막 편집 후 _AUTOSAVE_DELAY_MS 경과 시 저장)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(_AUTOSAVE_DELAY_MS)
        self._autosave_timer.timeout.connect(self._do_autosave)

        # ----- Top toolbar-ish row -----
        top = QWidget()
        top_l = QHBoxLayout(top)
        top_l.setContentsMargins(8, 8, 8, 8)

        self.btn_open = QPushButton("폴더 열기")
        self.btn_reload = QPushButton("다시 로드")

        self.btn_csl_folder = QPushButton("CSL 폴더 선택...")
        self.lbl_csl_folder = QLabel("CSL 폴더: (미지정)")
        self.lbl_csl_folder.setToolTip("이 폴더 안의 .csl 파일이 스타일 목록에 표시됩니다")

        self.btn_undo = QPushButton("↩ 되돌리기")
        self.btn_undo.setToolTip("이전 상태로 되돌리기 (Ctrl+Z)")
        self.btn_undo.setEnabled(False)

        self.btn_redo = QPushButton("↪ 다시실행")
        self.btn_redo.setToolTip("되돌리기 취소 (Ctrl+Y)")
        self.btn_redo.setEnabled(False)

        self.btn_save = QPushButton("저장(원본 RIS 반영)")
        self.btn_export = QPushButton("내보내기(output)")
        self.btn_copy_all = QPushButton("전체 참고문헌 복사")

        self.style_combo = QComboBox()
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["author_year", "year_author", "title", "none"])

        top_l.addWidget(self.btn_open)
        top_l.addWidget(self.btn_reload)
        top_l.addWidget(self.btn_csl_folder)
        top_l.addWidget(self.lbl_csl_folder)
        top_l.addSpacing(8)
        top_l.addWidget(self.btn_undo)
        top_l.addWidget(self.btn_redo)
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
        self.editor_form = form

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

        self.editor_field_widgets = {
            "type": self.type_combo,
            "title": self.title_edit,
            "title_alt": self.title_alt_edit,
            "year": self.year_spin,
            "authors": self.authors_edit,
            "container_title": self.container_edit,
            "volume": self.volume_edit,
            "issue": self.issue_edit,
            "pages": self.pages_edit,
            "doi": self.doi_edit,
            "url": self.url_edit,
            "publisher": self.publisher_edit,
            "institution": self.institution_edit,
        }

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

        # CSL 폴더 레이블 초기화
        self._update_csl_folder_label()

        # Populate style list (also restores last style)
        self._reload_styles()
        self._apply_editor_field_visibility_for_style()

        # Wire signals
        self.btn_open.clicked.connect(self.on_open_folder)
        self.btn_reload.clicked.connect(self.on_reload)
        self.btn_csl_folder.clicked.connect(self.on_select_csl_folder)
        self.btn_undo.clicked.connect(self.on_undo)
        self.btn_redo.clicked.connect(self.on_redo)
        self.btn_save.clicked.connect(self.on_save_back)

        # 키보드 단축키
        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self.on_undo)
        QShortcut(QKeySequence("Ctrl+Y"), self).activated.connect(self.on_redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self).activated.connect(self.on_redo)
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
        builtin + 사용자 지정 CSL 폴더(+ fallback: app/user styles)의 .csl 파일을 콤보박스에 로드.
        - config의 last_style 우선 적용
        """
        from pathlib import Path

        prev = self._current_style_selector() if self.style_combo.count() else None

        self.style_combo.clear()

        extra_dir: Path | None = None
        if self.cfg.csl_folder:
            p = Path(self.cfg.csl_folder)
            if p.is_dir():
                extra_dir = p

        styles = list_styles(include_builtin=True, include_csl=True, extra_csl_dir=extra_dir)

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

    def _apply_editor_field_visibility_for_style(
        self, record_type: Optional[RecordType] = None
    ):
        """
        (스타일 × RecordType) 교집합으로 편집 필드 노출 결정.
        - record_type이 None이면 현재 레코드의 타입 사용 (없으면 전체 표시)
        - builtin 스타일: 타입 기반 필드만 표시
        - csl 스타일: (타입 기반 필드) ∩ (CSL에서 사용하는 필드)
        """
        # 현재 타입 결정
        if record_type is None and self.current_record:
            record_type = self.current_record.type

        if record_type is not None:
            type_fields: set = fields_for_type(record_type)
        else:
            type_fields = set(self.editor_field_widgets.keys())

        style_selector = self._current_style_selector()

        if style_selector.startswith("csl:"):
            csl_path = style_selector.split(":", 1)[1]
            csl_fields = editor_fields_for_csl(csl_path)
            if csl_fields:
                visible_fields = type_fields & csl_fields
            else:
                visible_fields = type_fields
        else:
            visible_fields = type_fields

        # type 선택기는 항상 표시
        visible_fields = visible_fields | {"type"}

        for key, widget in self.editor_field_widgets.items():
            self.editor_form.setRowVisible(widget, key in visible_fields)

    def _update_csl_folder_label(self):
        folder = self.cfg.csl_folder
        if folder:
            from pathlib import Path
            p = Path(folder)
            count = len(list(p.glob("*.csl"))) if p.is_dir() else 0
            self.lbl_csl_folder.setText(f"CSL 폴더: {p.name}  ({count}개)")
            self.lbl_csl_folder.setToolTip(str(p))
        else:
            self.lbl_csl_folder.setText("CSL 폴더: (미지정)")
            self.lbl_csl_folder.setToolTip("이 폴더 안의 .csl 파일이 스타일 목록에 표시됩니다")

    def on_select_csl_folder(self):
        """
        사용자가 CSL 파일이 들어있는 폴더를 직접 선택.
        선택 즉시 스타일 목록이 갱신된다.
        """
        folder = QFileDialog.getExistingDirectory(self, "CSL 스타일 폴더 선택", self.cfg.csl_folder or "")
        if not folder:
            return

        self.cfg.csl_folder = folder
        self._persist_ui_config()
        self._update_csl_folder_label()
        self._reload_styles()
        self._apply_editor_field_visibility_for_style()

        if self.project:
            self.project.settings.style_id = self._current_style_selector()
            self.project.settings.sort_mode = self._current_sort_mode()  # type: ignore
            self._refresh_all_preview()
            self._refresh_one_preview()

    # -----------------------------
    # Undo / Redo
    # -----------------------------

    def _push_undo_snapshot(self, r: Record) -> None:
        """현재 Record 상태를 undo 스택에 저장하고 redo 스택을 초기화."""
        stack = self._undo_stacks.setdefault(r.id, [])
        stack.append(r.to_dict())
        if len(stack) > _MAX_UNDO_DEPTH:
            stack.pop(0)
        # 새 액션이 생겼으므로 redo 스택 삭제
        self._redo_stacks.pop(r.id, None)
        self._update_undo_redo_buttons(r.id)

    def _apply_record_snapshot(self, target: Record, snap: dict) -> None:
        """snap 딕셔너리의 내용을 target Record에 덮어씀."""
        src = Record.from_dict(snap)
        target.type = src.type
        target.title = src.title
        target.title_alt = src.title_alt
        target.year = src.year
        target.authors = src.authors
        target.container_title = src.container_title
        target.volume = src.volume
        target.issue = src.issue
        target.pages = src.pages
        target.doi = src.doi
        target.url = src.url
        target.publisher = src.publisher
        target.institution = src.institution
        target.dirty = True

    def _update_undo_redo_buttons(self, record_id: Optional[str]) -> None:
        can_undo = bool(record_id and self._undo_stacks.get(record_id))
        can_redo = bool(record_id and self._redo_stacks.get(record_id))
        self.btn_undo.setEnabled(can_undo)
        self.btn_redo.setEnabled(can_redo)

    def on_undo(self) -> None:
        r = self.current_record
        if not r:
            return
        stack = self._undo_stacks.get(r.id, [])
        if not stack:
            return
        # 현재 상태 → redo 스택
        redo_stack = self._redo_stacks.setdefault(r.id, [])
        redo_stack.append(r.to_dict())
        # 이전 상태 복원
        snap = stack.pop()
        self._apply_record_snapshot(r, snap)
        self._last_undo_push.pop(r.id, None)  # 복원 후 다음 편집은 새 스냅샷으로
        self._sync_editor_from_record(r)

    def on_redo(self) -> None:
        r = self.current_record
        if not r:
            return
        stack = self._redo_stacks.get(r.id, [])
        if not stack:
            return
        # 현재 상태 → undo 스택
        undo_stack = self._undo_stacks.setdefault(r.id, [])
        undo_stack.append(r.to_dict())
        # redo 상태 복원
        snap = stack.pop()
        self._apply_record_snapshot(r, snap)
        self._last_undo_push.pop(r.id, None)
        self._sync_editor_from_record(r)

    def _sync_editor_from_record(self, r: Record) -> None:
        """Record 상태를 에디터 UI에 반영하고 미리보기 갱신."""
        self._load_record_into_editor(r)
        self._apply_editor_field_visibility_for_style(record_type=r.type)
        normalize_record(r, mark_dirty=False)
        validate_record(r)
        idx = self.list_records.currentRow()
        if idx >= 0:
            self.list_records.item(idx).setText(_record_label(r))
        self._refresh_one_preview()
        self._refresh_all_preview()
        self._refresh_issues_view(r)
        self._update_undo_redo_buttons(r.id)

    # -----------------------------
    # Auto-save
    # -----------------------------

    def _do_autosave(self) -> None:
        """dirty 레코드를 조용히 원본 파일에 저장."""
        if not self.project:
            return
        dirty = [rec for rec in self.project.records if rec.dirty]
        if not dirty:
            return
        try:
            save_project_back_to_sources(self.project, only_dirty=True, encoding="utf-8")
            orig_title = self.windowTitle().replace(" [자동저장됨]", "")
            self.setWindowTitle(orig_title + " [자동저장됨]")
            QTimer.singleShot(2000, lambda: self.setWindowTitle(orig_title))
        except Exception:
            pass  # 자동저장 실패는 조용히 무시

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
            self._update_undo_redo_buttons(None)
            return

        r = self.project.records[row]
        self.current_record = r
        self._load_record_into_editor(r)
        self._apply_editor_field_visibility_for_style(record_type=r.type)
        self._refresh_one_preview()
        self._refresh_issues_view(r)
        self._update_undo_redo_buttons(r.id)

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
                new_type = RecordType(tval)
            except Exception:
                new_type = RecordType.OTHER

            # ─── Undo 스냅샷 (변경 적용 전) ───────────────────────────────
            type_changed = (new_type != r.type)
            now = time.monotonic()
            last_push = self._last_undo_push.get(r.id, 0.0)
            if type_changed or (now - last_push > _UNDO_DEBOUNCE):
                self._push_undo_snapshot(r)
                self._last_undo_push[r.id] = now
            # ──────────────────────────────────────────────────────────────

            r.type = new_type
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

            # 타입이 바뀌면 표시 필드도 즉시 갱신
            if type_changed:
                self._apply_editor_field_visibility_for_style(record_type=r.type)

            idx = self.list_records.currentRow()
            if idx >= 0:
                self.list_records.item(idx).setText(_record_label(r))

            self._refresh_one_preview()
            self._refresh_all_preview()
            self._refresh_issues_view(r)

            # 자동저장 타이머 재시작
            self._autosave_timer.start()

        except Exception as e:
            QMessageBox.warning(self, "편집 반영 실패", f"{type(e).__name__}: {e}")

    def on_style_or_sort_changed(self):
        """
        스타일/정렬 변경:
        - config에 저장
        - 프로젝트 있으면 설정 반영 + 미리보기 갱신
        """
        self._persist_ui_config()
        self._apply_editor_field_visibility_for_style()

        if self.project:
            self.project.settings.style_id = self._current_style_selector()
            self.project.settings.sort_mode = self._current_sort_mode()  # type: ignore
            self._refresh_all_preview()
            self._refresh_one_preview()

    def _get_csl_relevant_fields(self):
        """
        현재 선택된 스타일이 CSL이면 해당 스타일에서 사용하는 editor 필드 Set을 반환.
        builtin 스타일이거나 CSL 필드를 파악할 수 없으면 None 반환.
        """
        style_selector = self._current_style_selector()
        if not style_selector.startswith("csl:"):
            return None
        csl_path = style_selector.split(":", 1)[1]
        fields = editor_fields_for_csl(csl_path)
        return fields if fields else None

    def _refresh_issues_view(self, r: Record):
        all_issues = r.issues or []
        relevant_fields = self._get_csl_relevant_fields()

        if relevant_fields is not None:
            visible_issues = filter_issues_for_fields(all_issues, relevant_fields)
            hidden_count = len(all_issues) - len(visible_issues)
        else:
            visible_issues = all_issues
            hidden_count = 0

        lines: List[str] = []
        for it in visible_issues:
            lines.append(f"[{it.severity.value.upper():5}] {it.field}: {it.message}")
        if not lines:
            lines = ["(이슈 없음)"]
        if hidden_count > 0:
            lines.append(f"\n※ {hidden_count}개 이슈 숨김 (현재 CSL 스타일에서 사용하지 않는 필드)")
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
