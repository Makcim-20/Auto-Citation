from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import re
import shutil

from .model import Record, PersonName, SourceFormat, RecordType


# RIS line format: "TY  - JOUR" (tag 2 chars, two spaces, dash)
RIS_LINE_RE = re.compile(r"^([A-Z0-9]{2})\s{2}-\s?(.*)$")
CONTINUATION_RE = re.compile(r"^\s{6}(.*)$")  # continuation lines (rare but exists)


# --- Type mapping (minimal, extend later) ---
RIS_TY_TO_RECORDTYPE = {
    "JOUR": RecordType.JOURNAL_ARTICLE,
    "JFULL": RecordType.JOURNAL_ARTICLE,
    "THES": RecordType.THESIS,
    "DISS": RecordType.THESIS,
    "BOOK": RecordType.BOOK,
    "CHAP": RecordType.BOOK_CHAPTER,
    "CPAPER": RecordType.CONFERENCE_PAPER,
    "CONF": RecordType.CONFERENCE_PAPER,
    "RPRT": RecordType.REPORT,
    "WEB": RecordType.WEBPAGE,
}

RECORDTYPE_TO_RIS_TY = {
    RecordType.JOURNAL_ARTICLE: "JOUR",
    RecordType.THESIS: "THES",
    RecordType.BOOK: "BOOK",
    RecordType.BOOK_CHAPTER: "CHAP",
    RecordType.CONFERENCE_PAPER: "CPAPER",
    RecordType.REPORT: "RPRT",
    RecordType.WEBPAGE: "WEB",
    RecordType.OTHER: "GEN",
}


# --- Encoding helpers ---
ENCODINGS_TO_TRY = ["utf-8-sig", "utf-8", "cp949", "euc-kr"]


def read_text_guess(path: Union[str, Path]) -> Tuple[str, str]:
    """
    Read text file with best-effort encoding guessing.
    Returns (text, encoding_used).
    """
    p = Path(path)
    data = p.read_bytes()
    for enc in ENCODINGS_TO_TRY:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    # last resort: replace
    return data.decode("utf-8", errors="replace"), "utf-8(replace)"


def _clean(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = s.replace("\u00a0", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return s or None


def _add_raw(raw: Dict[str, Any], tag: str, value: str) -> None:
    """
    raw_fields stores all tags losslessly.
    If tag repeats, store list.
    """
    if tag in raw:
        if isinstance(raw[tag], list):
            raw[tag].append(value)
        else:
            raw[tag] = [raw[tag], value]
    else:
        raw[tag] = value


def _get_first(raw: Dict[str, Any], *tags: str) -> Optional[str]:
    for t in tags:
        v = raw.get(t)
        if v is None:
            continue
        if isinstance(v, list):
            # take first non-empty
            for it in v:
                itc = _clean(str(it))
                if itc:
                    return itc
            continue
        return _clean(str(v))
    return None


def _get_all(raw: Dict[str, Any], tag: str) -> List[str]:
    v = raw.get(tag)
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if _clean(str(x))]
    if _clean(str(v)):
        return [str(v)]
    return []


def _parse_year(raw: Dict[str, Any]) -> Optional[int]:
    """
    RIS year tags: PY, Y1, DA (sometimes).
    Accept 4-digit year at start.
    """
    for tag in ("PY", "Y1", "DA"):
        v = _get_first(raw, tag)
        if not v:
            continue
        m = re.search(r"(19\d{2}|20\d{2})", v)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return None


_LA_NORMALIZE: Dict[str, str] = {
    # 한국어
    "korean": "ko", "kor": "ko", "ko": "ko", "한국어": "ko",
    # 영어
    "english": "en", "eng": "en", "en": "en",
    # 중국어
    "chinese": "zh", "chi": "zh", "zho": "zh", "zh": "zh",
    # 일본어
    "japanese": "ja", "jpn": "ja", "ja": "ja",
}


def _parse_language(raw: Dict[str, Any]) -> Optional[str]:
    """RIS LA 태그 → 정규화된 언어 코드 (ko/en/zh/ja/...)."""
    v = _get_first(raw, "LA")
    if not v:
        return None
    normalized = _LA_NORMALIZE.get(v.strip().lower())
    return normalized or v.strip().lower()[:10]


def _parse_pages(raw: Dict[str, Any]) -> Optional[str]:
    sp = _get_first(raw, "SP")
    ep = _get_first(raw, "EP")
    if sp and ep:
        return f"{sp}-{ep}"
    return _get_first(raw, "SP") or _get_first(raw, "EP")


def _parse_authors(raw: Dict[str, Any]) -> List[PersonName]:
    """
    RIS authors tags: AU, A1 (primary author), A2 (secondary), etc.
    We'll treat AU and A1 as authors for MVP.
    """
    names = _get_all(raw, "AU") + _get_all(raw, "A1")
    out: List[PersonName] = []
    for n in names:
        n = _clean(n)
        if not n:
            continue
        out.append(PersonName(literal=n, role="author"))
    return out


def parse_ris_text(
    text: str,
    *,
    source_file: Optional[str] = None,
) -> List[Record]:
    """
    Parse RIS text into list[Record].
    """
    lines = text.splitlines()

    records_raw: List[Dict[str, Any]] = []
    cur: Dict[str, Any] = {}
    in_record = False
    last_tag: Optional[str] = None

    for line in lines:
        line = line.rstrip("\n\r")

        m = RIS_LINE_RE.match(line)
        if m:
            tag, value = m.group(1), m.group(2)
            value = value.rstrip()

            if tag == "TY":
                # start new record
                if in_record and cur:
                    records_raw.append(cur)
                cur = {}
                in_record = True
                last_tag = "TY"
                _add_raw(cur, "TY", value)
                continue

            if not in_record:
                # ignore garbage before first TY
                continue

            _add_raw(cur, tag, value)
            last_tag = tag

            if tag == "ER":
                # record end
                records_raw.append(cur)
                cur = {}
                in_record = False
                last_tag = None

            continue

        # continuation line (optional)
        cm = CONTINUATION_RE.match(line)
        if cm and in_record and last_tag:
            extra = cm.group(1).rstrip()
            # append to last tag's latest value
            prev = cur.get(last_tag)
            if prev is None:
                _add_raw(cur, last_tag, extra)
            elif isinstance(prev, list):
                prev[-1] = f"{prev[-1]} {extra}".strip()
            else:
                cur[last_tag] = f"{prev} {extra}".strip()
            continue

        # otherwise ignore unknown line formatting

    # if file ended mid-record without ER
    if in_record and cur:
        records_raw.append(cur)

    # Convert raw dict -> Record
    records: List[Record] = []
    for idx, raw in enumerate(records_raw):
        ty = _get_first(raw, "TY") or "GEN"
        rtype = RIS_TY_TO_RECORDTYPE.get(ty.upper(), RecordType.OTHER)

        title = _get_first(raw, "TI", "T1")
        title_alt = _get_first(raw, "T2")  # sometimes container, but keep as alt for now

        container = _get_first(raw, "JO", "JF", "T2", "BT", "B1")
        volume = _get_first(raw, "VL")
        issue = _get_first(raw, "IS")
        pages = _parse_pages(raw)

        doi = _get_first(raw, "DO")
        url = _get_first(raw, "UR")

        publisher = _get_first(raw, "PB")
        institution = _get_first(raw, "IN")  # not standard, but appears in some exports

        year = _parse_year(raw)
        authors = _parse_authors(raw)

        rec = Record.new(
            title=title,
            year=year,
            authors=authors,
            container_title=container,
            source_file=source_file,
            source_format=SourceFormat.RIS,
            source_record_index=idx,
            type=rtype,
            raw_fields=dict(raw),  # lossless
        )
        rec.title_alt = title_alt
        rec.volume = volume
        rec.issue = issue
        rec.pages = pages
        rec.doi = doi
        rec.url = url
        rec.publisher = publisher
        rec.institution = institution
        rec.language = _parse_language(raw)

        records.append(rec)

    return records


def parse_ris(path: Union[str, Path]) -> Tuple[List[Record], str]:
    """
    Parse RIS file. Returns (records, encoding_used).
    """
    p = Path(path)
    text, enc = read_text_guess(p)
    recs = parse_ris_text(text, source_file=str(p))
    return recs, enc


# --- Writing ---
def _format_ris_line(tag: str, value: str) -> str:
    return f"{tag}  - {value}"


def _write_tag_lines(lines: List[str], tag: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, list):
        for v in value:
            if v is None:
                continue
            vs = str(v).strip()
            if vs:
                lines.append(_format_ris_line(tag, vs))
    else:
        vs = str(value).strip()
        if vs:
            lines.append(_format_ris_line(tag, vs))


def record_to_ris_lines(record: Record) -> List[str]:
    """
    Convert one Record to RIS lines.
    Preserve unknown fields from raw_fields as much as possible.
    MVP policy:
      - Start with TY
      - Write canonical fields (title/authors/year/container/vol/issue/pages/doi/url/publisher)
      - Then write remaining raw_fields that are not overwritten
      - End with ER
    """
    raw = dict(record.raw_fields or {})
    lines: List[str] = []

    # TY
    ty = RECORDTYPE_TO_RIS_TY.get(record.type, "GEN")
    lines.append(_format_ris_line("TY", ty))

    # Canonical fields
    if record.title:
        lines.append(_format_ris_line("TI", record.title))
    if record.title_alt:
        lines.append(_format_ris_line("T1", record.title_alt))  # as alternate title slot

    # Authors
    for a in record.authors:
        nm = a.display()
        if nm:
            lines.append(_format_ris_line("AU", nm))

    # Year (RIS often uses PY)
    if record.year:
        lines.append(_format_ris_line("PY", str(record.year)))

    # Container (Journal/Book title)
    if record.container_title:
        # JO is common for journal
        lines.append(_format_ris_line("JO", record.container_title))

    # Volume/Issue
    if record.volume:
        lines.append(_format_ris_line("VL", str(record.volume)))
    if record.issue:
        lines.append(_format_ris_line("IS", str(record.issue)))

    # Pages: split into SP/EP if it looks like range
    if record.pages:
        m = re.match(r"^\s*(\d+)\s*[-–]\s*(\d+)\s*$", record.pages)
        if m:
            lines.append(_format_ris_line("SP", m.group(1)))
            lines.append(_format_ris_line("EP", m.group(2)))
        else:
            lines.append(_format_ris_line("SP", record.pages))

    if record.publisher:
        lines.append(_format_ris_line("PB", record.publisher))
    if record.institution:
        lines.append(_format_ris_line("IN", record.institution))
    if record.language:
        lines.append(_format_ris_line("LA", record.language))

    if record.doi:
        lines.append(_format_ris_line("DO", record.doi))
    if record.url:
        lines.append(_format_ris_line("UR", record.url))

    # Remove tags that we already emitted from raw (to reduce duplication)
    # (We intentionally keep raw_fields to preserve extras, but avoid obvious duplicates.)
    for t in ["TY", "TI", "T1", "AU", "A1", "PY", "Y1", "DA", "JO", "JF", "T2", "VL", "IS", "SP", "EP", "PB", "IN", "LA", "DO", "UR", "ER"]:
        raw.pop(t, None)

    # Write remaining raw tags (lossless-ish)
    # Stable order: by tag name
    for tag in sorted(raw.keys()):
        _write_tag_lines(lines, tag, raw[tag])

    # ER
    lines.append(_format_ris_line("ER", ""))

    return lines


def write_ris(
    path: Union[str, Path],
    records: List[Record],
    *,
    backup: bool = True,
    encoding: str = "utf-8",
) -> None:
    """
    Write records back to a RIS file.
    Creates .bak before overwriting if backup=True.
    """
    p = Path(path)

    if backup and p.exists():
        bak = p.with_suffix(p.suffix + ".bak")
        shutil.copy2(p, bak)

    out_lines: List[str] = []
    for rec in records:
        out_lines.extend(record_to_ris_lines(rec))
        out_lines.append("")  # blank line between records for readability

    text = "\n".join(out_lines).rstrip() + "\n"
    p.write_text(text, encoding=encoding, errors="strict")
