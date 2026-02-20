from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from .paths import user_data_dir


@dataclass
class AppConfig:
    last_style: str = "builtin:kr_default"
    last_sort: str = "author_year"
    csl_folder: str = ""  # 사용자가 지정한 CSL 파일 폴더 경로


def config_path() -> Path:
    d = user_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "config.json"


def load_config() -> AppConfig:
    p = config_path()
    if not p.exists():
        return AppConfig()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return AppConfig(
            last_style=str(data.get("last_style", "builtin:kr_default")),
            last_sort=str(data.get("last_sort", "author_year")),
            csl_folder=str(data.get("csl_folder", "")),
        )
    except Exception:
        return AppConfig()


def save_config(cfg: AppConfig) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
