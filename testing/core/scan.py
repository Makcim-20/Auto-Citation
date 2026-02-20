from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional, Sequence


SUPPORTED_EXTS_DEFAULT = [".ris"]  # MVP는 RIS만


def scan_folder(
    folder: str | Path,
    *,
    exts: Optional[Sequence[str]] = None,
    recursive: bool = True,
    include_hidden: bool = False,
) -> List[Path]:
    """
    Scan a folder and return a sorted list of supported bibliography files.
    """
    root = Path(folder).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Folder not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Not a folder: {root}")

    exts = [e.lower() for e in (exts or SUPPORTED_EXTS_DEFAULT)]

    def is_hidden(p: Path) -> bool:
        return any(part.startswith(".") for part in p.parts)

    paths: List[Path] = []
    iterator: Iterable[Path] = root.rglob("*") if recursive else root.glob("*")
    for p in iterator:
        if not p.is_file():
            continue
        if not include_hidden and is_hidden(p.relative_to(root)):
            continue
        if p.suffix.lower() in exts:
            paths.append(p)

    return sorted(paths, key=lambda x: str(x).lower())
