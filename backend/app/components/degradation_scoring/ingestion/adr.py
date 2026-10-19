# ADR index: parses decision records (MADR front matter or Nygard "## Status") and C2's
# element -> violated ADR links (adr_refs). C4 never decides a violation itself.

import re
from collections.abc import Mapping

import structlog

from app.components.degradation_scoring.ingestion.errors import AdrIndexError
from app.components.degradation_scoring.models import AdrIndex, AdrRecord

log = structlog.get_logger(__name__)

STATUSES = ("accepted", "proposed", "deprecated", "superseded", "rejected")
SCOPES = ("system", "component", "module", "local")
FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
NYGARD_STATUS = re.compile(r"^#+\s*status\s*\n+\s*(\S[^\n]*)", re.IGNORECASE | re.MULTILINE)
TITLE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def _front_matter(text: str) -> dict[str, str]:
    match = FRONT_MATTER.match(text)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip().lower()] = value.strip().strip("\"'")
    return fields


def normalise_status(raw: str | None) -> str:
    # "Superseded by ADR-0007" -> "superseded"; anything else unknown is "unknown"
    word = (raw or "").strip().lower()
    return next((status for status in STATUSES if word.startswith(status)), "unknown")


def normalise_scope(raw: str | None) -> str:
    word = (raw or "").strip().lower()
    return word if word in SCOPES else "unspecified"


def parse_adr(adr_id: str, text: str) -> AdrRecord:
    # status from front matter, else the Nygard "## Status" section; scope only from front
    # matter (Nygard has none); unknown values are logged and get the table's lowest weight
    fields = _front_matter(text)
    raw_status = fields.get("status")
    if raw_status is None and (match := NYGARD_STATUS.search(text)):
        raw_status = match.group(1)
    status, scope = normalise_status(raw_status), normalise_scope(fields.get("scope"))
    if status == "unknown":
        log.warning("adr_status_unknown", reason="adr_status_unknown", adr=adr_id, raw=raw_status)
    title = match.group(1).strip() if (match := TITLE.search(text)) else adr_id
    return AdrRecord(adr_id=adr_id, title=title, status=status, scope=scope)


def parse_index(document: object) -> AdrIndex:
    # {"adrs": [{"id", "text"}], "links": {element: [adr ids]}} -> AdrIndex
    if not isinstance(document, Mapping) or not isinstance(document.get("adrs"), list):
        raise AdrIndexError("ADR index needs an 'adrs' list")
    adrs: dict[str, AdrRecord] = {}
    for entry in document["adrs"]:
        if not isinstance(entry, Mapping) or not entry.get("id") or "text" not in entry:
            raise AdrIndexError(f"ADR entry needs 'id' and 'text': {entry!r:.80}")
        adr_id = str(entry["id"])
        if adr_id in adrs:
            raise AdrIndexError(f"duplicate ADR id {adr_id!r}")
        adrs[adr_id] = parse_adr(adr_id, str(entry["text"]))
    raw_links = document.get("links") or {}
    if not isinstance(raw_links, Mapping):
        raise AdrIndexError("ADR index 'links' must map element ids to ADR id lists")
    links = {str(element): sorted({str(i) for i in ids}) for element, ids in raw_links.items()}
    return AdrIndex(adrs=adrs, links=links)
