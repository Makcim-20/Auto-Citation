from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Literal, Iterable, Set
import xml.etree.ElementTree as ET

from .paths import app_styles_dir, user_styles_dir
from .model import RecordType


StyleKind = Literal["builtin", "csl"]


# RecordType별로 의미 있는 에디터 필드 집합
# "type" 필드는 항상 표시되므로 여기엔 포함하지 않는다.
TYPE_FIELDS: Dict[RecordType, Set[str]] = {
    RecordType.JOURNAL_ARTICLE: {
        "title", "title_alt", "authors", "year",
        "container_title", "volume", "issue", "pages", "doi", "url",
    },
    RecordType.BOOK: {
        "title", "title_alt", "authors", "year",
        "publisher", "doi", "url",
    },
    RecordType.BOOK_CHAPTER: {
        "title", "title_alt", "authors", "year",
        "container_title", "publisher", "pages", "doi", "url",
    },
    RecordType.CONFERENCE_PAPER: {
        "title", "title_alt", "authors", "year",
        "container_title", "pages", "publisher", "doi", "url",
    },
    RecordType.THESIS: {
        "title", "title_alt", "authors", "year",
        "institution", "publisher", "url",
    },
    RecordType.REPORT: {
        "title", "title_alt", "authors", "year",
        "institution", "publisher", "doi", "url",
    },
    RecordType.WEBPAGE: {
        "title", "title_alt", "authors", "year", "url",
    },
    RecordType.OTHER: {
        "title", "title_alt", "authors", "year",
        "container_title", "volume", "issue", "pages",
        "doi", "url", "publisher", "institution",
    },
}


def fields_for_type(record_type: RecordType) -> Set[str]:
    """해당 RecordType에서 의미 있는 에디터 필드 키 집합 반환."""
    return set(TYPE_FIELDS.get(record_type, TYPE_FIELDS[RecordType.OTHER]))


@dataclass(frozen=True)
class StyleRef:
    kind: StyleKind
    key: str
    name: str
    path: Optional[str] = None

    def to_selector_value(self) -> str:
        if self.kind == "builtin":
            return f"builtin:{self.key}"
        return f"csl:{self.path or self.key}"


def _safe_text(x: Optional[str]) -> str:
    return (x or "").strip()


def _split_csl_variables(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [v.strip() for v in value.split() if v.strip()]


@lru_cache(maxsize=64)
def csl_variables_used(csl_path: str | Path) -> Set[str]:
    """
    Return variable names used by a CSL style.

    We scan all XML elements for a `variable` attribute and split on spaces,
    which matches CSL usage patterns like: variable="author editor".
    """
    p = Path(csl_path).expanduser().resolve()
    used: Set[str] = set()

    try:
        tree = ET.parse(str(p))
        root = tree.getroot()
        for el in root.iter():
            for v in _split_csl_variables(el.attrib.get("variable")):
                used.add(v)
    except Exception:
        return set()

    return used


# RecordType → CSL type name (used for per-type XML parsing)
_RECORDTYPE_TO_CSL_TYPE: Dict[str, str] = {
    "journalArticle":   "article-journal",
    "book":             "book",
    "bookChapter":      "chapter",
    "conferencePaper":  "paper-conference",
    "thesis":           "thesis",
    "report":           "report",
    "webpage":          "webpage",
    "other":            "article",
}


def _ltag(tag: str) -> str:
    """XML 태그에서 네임스페이스 제거."""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _el_vars(el: ET.Element) -> Set[str]:
    """element의 variable 속성값을 공백 분리해서 반환."""
    raw = el.attrib.get("variable") or ""
    return {v for v in raw.split() if v}


def _collect_all_vars(el: ET.Element, out: Set[str]) -> None:
    """서브트리 전체에서 모든 variable 참조를 무조건 수집."""
    out.update(_el_vars(el))
    for child in el:
        _collect_all_vars(child, out)


def _collect_vars_for_type(el: ET.Element, csl_type: str, out: Set[str]) -> None:
    """
    CSL XML 트리를 순회하며 csl_type에 해당하는 variable 참조만 수집.

    규칙:
    - <choose> 밖의 variable → 항상 수집
    - <choose><if type="X"> → X에 csl_type이 포함될 때 수집
    - <choose><else-if type="X"> → 위 if가 미매칭이고 X에 csl_type 포함 시 수집
    - <choose><else> → 어떤 if/else-if도 매칭 안 됐을 때 수집
    - type 조건 없는 <if variable="..."> 등 → 항상 수집 (조건부지만 타입 무관)
    """
    tag = _ltag(el.tag)

    if tag != "choose":
        out.update(_el_vars(el))
        for child in el:
            _collect_vars_for_type(child, csl_type, out)
        return

    # <choose> 처리
    has_type_cond = False
    matched = False

    for child in el:
        child_tag = _ltag(child.tag)

        if child_tag in ("if", "else-if"):
            types_str = child.attrib.get("type", "")
            if types_str:
                # 타입 조건이 있는 분기
                has_type_cond = True
                if not matched and csl_type in types_str.split():
                    matched = True
                    _collect_all_vars(child, out)
                # 매칭 안 된 분기는 skip
            else:
                # 타입 조건 없음(variable 조건 등) → 항상 수집
                _collect_vars_for_type(child, csl_type, out)

        elif child_tag == "else":
            # 타입 기반 choose였고 아무것도 매칭 안 됐을 때
            if has_type_cond and not matched:
                _collect_all_vars(child, out)
            elif not has_type_cond:
                _collect_vars_for_type(child, csl_type, out)


@lru_cache(maxsize=256)
def csl_variables_for_type(csl_path: str, csl_type: str) -> Set[str]:
    """
    CSL 파일에서 특정 CSL 타입(예: "article-journal")에 해당하는 variable 집합 반환.
    <choose><if type="..."> 블록을 해석해서 타입별 분기를 정확히 추적한다.
    csl_path는 절대 경로 문자열(캐시 안정성을 위해)이어야 한다.
    """
    try:
        tree = ET.parse(csl_path)
        root = tree.getroot()
    except Exception:
        return set()

    out: Set[str] = set()
    _collect_vars_for_type(root, csl_type, out)
    return out


# UI editor field keys used by MainWindow
_CSL_VAR_TO_EDITOR_FIELDS: Dict[str, Set[str]] = {
    "title": {"title"},
    "title-short": {"title_alt"},
    "author": {"authors"},
    "issued": {"year"},
    "container-title": {"container_title"},
    "collection-title": {"container_title"},
    "volume": {"volume"},
    "issue": {"issue"},
    "page": {"pages"},
    "DOI": {"doi"},
    "URL": {"url"},
    "publisher": {"publisher"},
    "institution": {"institution"},
    "language": {"language"},
}


def editor_fields_for_csl(
    csl_path: str | Path,
    record_type: Optional[RecordType] = None,
) -> Set[str]:
    """
    CSL 파일 + (선택) RecordType → 에디터에 표시할 필드 키 집합.

    record_type이 주어지면 <choose><if type="..."> 블록을 해석해 타입별로
    실제 사용되는 변수만 추출한다. 주어지지 않으면 전체 변수 합집합을 사용.
    """
    resolved = str(Path(csl_path).expanduser().resolve())

    if record_type is not None:
        csl_type = _RECORDTYPE_TO_CSL_TYPE.get(record_type.value, "article")
        vars_used = csl_variables_for_type(resolved, csl_type)
    else:
        vars_used = csl_variables_used(resolved)

    if not vars_used:
        return set()

    fields: Set[str] = set()
    for var_name in vars_used:
        fields |= _CSL_VAR_TO_EDITOR_FIELDS.get(var_name, set())
    return fields


def read_csl_style_title(csl_path: str | Path) -> str:
    p = Path(csl_path)
    fallback = p.stem

    try:
        tree = ET.parse(str(p))
        root = tree.getroot()

        def local(tag: str) -> str:
            return tag.split("}", 1)[-1]

        info_el = None
        for el in root.iter():
            if local(el.tag) == "info":
                info_el = el
                break
        if info_el is None:
            return fallback

        for el in info_el.iter():
            if local(el.tag) == "title":
                t = _safe_text(el.text)
                return t or fallback

        return fallback
    except Exception:
        return fallback


def discover_csl_styles_in_dir(styles_dir: Path) -> List[StyleRef]:
    d = styles_dir.expanduser().resolve()
    if not d.exists() or not d.is_dir():
        return []

    out: List[StyleRef] = []
    for p in sorted(d.glob("*.csl"), key=lambda x: x.name.lower()):
        name = read_csl_style_title(p)
        out.append(StyleRef(kind="csl", key=str(p), name=name, path=str(p)))
    return out


def discover_csl_styles(styles_dirs: Iterable[Path]) -> List[StyleRef]:
    """
    여러 styles 디렉토리를 스캔해서 합치되,
    같은 파일명(stem)이 충돌하면 '먼저 들어온 것'이 우선.
    -> list_styles()에서 사용자 폴더를 먼저 넣으면 사용자가 우선권 가짐.
    """
    chosen: Dict[str, StyleRef] = {}
    for d in styles_dirs:
        for s in discover_csl_styles_in_dir(d):
            stem = Path(s.path or s.key).stem.lower()
            if stem not in chosen:
                chosen[stem] = s
    return list(chosen.values())


def discover_builtin_styles() -> List[StyleRef]:
    try:
        from .formatters import list_formatters
        m: Dict[str, str] = list_formatters()
    except Exception:
        m = {"kr_default": "국문 기본"}

    return [StyleRef(kind="builtin", key=k, name=v, path=None) for k, v in m.items()]


def list_styles(
    *,
    include_builtin: bool = True,
    include_csl: bool = True,
    extra_csl_dir: Optional[Path] = None,
) -> List[StyleRef]:
    """
    extra_csl_dir: 사용자가 UI에서 선택한 CSL 폴더. 우선순위 최상위.
    """
    styles: List[StyleRef] = []

    if include_builtin:
        styles.extend(discover_builtin_styles())

    if include_csl:
        dirs: List[Path] = []
        if extra_csl_dir is not None:
            dirs.append(extra_csl_dir)
        # 내장 폴더는 extra_csl_dir이 없을 때 fallback으로만 사용
        dirs.extend([user_styles_dir(), app_styles_dir()])
        styles.extend(discover_csl_styles(dirs))

    styles.sort(key=lambda s: (s.kind, s.name.lower()))
    return styles
