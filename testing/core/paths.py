from __future__ import annotations

import os
from pathlib import Path


def app_root() -> Path:
    """
    core/paths.py 기준으로 프로젝트 루트(core 폴더의 부모)를 앱 루트로 본다.
    """
    return Path(__file__).resolve().parents[1]


def app_styles_dir() -> Path:
    return app_root() / "styles"


def user_data_dir() -> Path:
    """
    간단한 크로스플랫폼 사용자 데이터 경로.
    - Windows: %APPDATA%/BiblioRef
    - others : ~/.biblioref
    """
    home = Path.home()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(home)))
        return base / "BiblioRef"
    return home / ".biblioref"


def user_styles_dir() -> Path:
    return user_data_dir() / "styles"
