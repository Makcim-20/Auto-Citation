from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Literal, Iterable, Set
import xml.etree.ElementTree as ET

from .paths import app_styles_dir, user_styles_dir


StyleKind = Literal["builtin", "csl"]


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
}


def editor_fields_for_csl(csl_path: str | Path) -> Set[str]:
    """
    Infer which GUI editor fields are relevant for the given CSL style.
    """
    vars_used = csl_variables_used(csl_path)
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
) -> List[StyleRef]:
    styles: List[StyleRef] = []

    if include_builtin:
        styles.extend(discover_builtin_styles())

    if include_csl:
        # ✅ 사용자 styles 먼저: 같은 이름이면 사용자 것이 우선
        dirs = [user_styles_dir(), app_styles_dir()]
        styles.extend(discover_csl_styles(dirs))

    styles.sort(key=lambda s: (s.kind, s.name.lower()))
    return styles
