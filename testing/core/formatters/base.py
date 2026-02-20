from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol, Sequence

from ..model import Record


@dataclass(frozen=True)
class FormatOptions:
    """
    Formatting options shared across styles.
    Keep it small in MVP, extend later.
    """
    # If True, show placeholders like [연도?] for missing fields in output
    show_missing_markers: bool = True

    # If True, include DOI/URL if present
    include_doi: bool = True
    include_url: bool = False

    # Author display policy
    # "all": list all authors
    # "et_al_3": show first author + '외' if >=3
    author_mode: str = "all"  # or "et_al_3"


class Formatter(Protocol):
    """
    Style plugin interface.
    """
    style_id: str
    display_name: str

    def format_one(self, record: Record, opts: FormatOptions) -> str:
        ...

    def format_list(self, records: Sequence[Record], opts: FormatOptions) -> str:
        ...
