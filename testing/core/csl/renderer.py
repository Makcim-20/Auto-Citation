from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Sequence, Optional

# citeproc-py
from citeproc import CitationStylesStyle, CitationStylesBibliography, Citation, CitationItem
from citeproc.source.json import CiteProcJSON


def _ensure_path(p: str | Path) -> Path:
    pp = Path(p).expanduser().resolve()
    if not pp.exists():
        raise FileNotFoundError(f"CSL style not found: {pp}")
    return pp


@lru_cache(maxsize=32)
def _load_style_cached(style_path: str, locale: str) -> CitationStylesStyle:
    """
    Style 파싱은 꽤 비싸서 캐시해둠.
    (style_path, locale) 조합 기준.
    """
    p = _ensure_path(style_path)
    # validate=True는 엄격하지만 느릴 수 있음. 배포시엔 False 추천.
    return CitationStylesStyle(str(p), validate=False, locale=locale)


def render_bibliography_text(
    style_path: str | Path,
    items: Sequence[Dict[str, Any]],
    *,
    locale: str = "ko-KR",
    as_plain_text: bool = True,
) -> str:
    """
    CSL 스타일 + CSL-JSON items -> 참고문헌 문자열(줄바꿈 구분) 반환.

    - items는 core/csl/adapter.py의 records_to_csl_items 결과물을 넣으면 됨.
    - locale은 style에서 terms(그리고, 외, 등) 처리에 영향을 줌.
    """
    style_path = str(_ensure_path(style_path))

    # citeproc expects a source object
    source = CiteProcJSON(list(items))

    style = _load_style_cached(style_path, locale)

    bibliography = CitationStylesBibliography(style, source, formatter="plain" if as_plain_text else "html")

    # citeproc는 "인용 처리 -> 참고문헌 생성" 형태로 동작하는데,
    # 우리가 원하는 건 "참고문헌 목록"이므로 모든 item을 1회 인용했다고 치고 등록시킨다.
    # CitationItem의 key는 item["id"]를 사용.
    citation_items = [CitationItem(item["id"]) for item in items if "id" in item]
    bibliography.register(Citation(citation_items))

    # 결과는 bibliography.bibliography()로 얻는다.
    entries = bibliography.bibliography()

    # citeproc-py 반환 타입은 formatter에 따라 다르지만, plain이면 보통 문자열로 변환 가능
    lines: List[str] = []
    for e in entries:
        lines.append(str(e).strip())

    # 빈 줄 제거
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)
