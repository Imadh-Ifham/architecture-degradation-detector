"""Redaction and endpoint extraction helpers.

Author: Imadh Ifham
Date: 2026-10-14
Description:
    Keeps credentials and sensitive configuration out of the analysis output,
    and recognises configured network endpoints inside configuration values.

    Two separate concerns live here because both are security-relevant and both
    are needed by more than one analyzer:

      * `sanitize_scalar` decides whether a value may be recorded at all.
      * `extract_endpoint_candidate` turns a value into a host/port/url without
        ever carrying credentials through.
"""

import re
from dataclasses import dataclass


# Key names whose values must never be recorded. Matched as whole words where
# possible so `AUTHOR` does not match `AUTH`.
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(?:^|[_\-.])("
    r"password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|"
    r"private[_-]?key|credential|credentials|bearer|cookie|session[_-]?key|"
    r"auth|authorization|client[_-]?secret|connection[_-]?string|dsn|sas|"
    r"account[_-]?key|signing[_-]?key|encryption[_-]?key|certificate[_-]?key|"
    r"keystore[_-]?pass|passphrase"
    r")(?:$|[_\-.])"
)

# A partial match is also treated as sensitive for keys ending in these, so
# `DB_PASSWORD_HASH` and `JWT_TOKEN` are caught.
SENSITIVE_KEY_SUFFIX_PATTERN = re.compile(
    r"(?i)(password|passwd|secret|token|apikey|api_key|credentials?|private_key)$"
)

_URL_PATTERN = re.compile(
    r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*)://(?P<rest>\S+)$"
)

# `host:port`, where the port must be numeric so an image tag such as
# `gcr.io/x/cart:1.2.3` and a Windows drive path are not mistaken for one.
_HOST_PORT_PATTERN = re.compile(
    r"^(?P<host>[A-Za-z0-9][A-Za-z0-9._\-]*):(?P<port>\d{1,5})$"
)

# Docker Compose port syntax: [host_ip:][host_port:]container_port[/protocol],
# with an optional range on either side.
_COMPOSE_PORT_PATTERN = re.compile(
    r"^(?:(?P<host_ip>\d{1,3}(?:\.\d{1,3}){3}):)?"
    r"(?:(?P<host_port>\d{1,5}(?:-\d{1,5})?):)?"
    r"(?P<container_port>\d{1,5}(?:-\d{1,5})?)"
    r"(?:/(?P<protocol>tcp|udp|sctp))?$",
    re.IGNORECASE,
)

DEFAULT_PORTS_BY_SCHEME: dict[str, int] = {
    "http": 80,
    "https": 443,
    "grpc": 443,
    "ws": 80,
    "wss": 443,
    "amqp": 5672,
    "redis": 6379,
    "postgres": 5432,
    "postgresql": 5432,
    "mysql": 3306,
    "mongodb": 27017,
    "kafka": 9092,
}


@dataclass(frozen=True)
class SanitizedValue:
    """A configuration value that has been cleared for storage."""

    value: str | None
    redacted: bool
    reason: str | None = None


@dataclass(frozen=True)
class EndpointCandidate:
    """A host/port/scheme found inside a configuration value."""

    host: str
    port: int | None = None
    scheme: str | None = None
    sanitized_value: str | None = None


def is_sensitive_key(key: str) -> bool:
    """Report whether a configuration key names something secret."""

    return bool(
        SENSITIVE_KEY_PATTERN.search(key)
        or SENSITIVE_KEY_SUFFIX_PATTERN.search(key)
    )


def sanitize_scalar(value: object, key: str | None = None) -> SanitizedValue:
    """Return a value that is safe to record, or a redacted placeholder.

    A value is redacted when its key looks sensitive, or when the value itself
    carries credentials (a url with a `user:password@` segment).
    """

    if value is None:
        return SanitizedValue(value=None, redacted=False)

    text = value if isinstance(value, str) else str(value)

    if key is not None and is_sensitive_key(key):
        return SanitizedValue(
            value=None,
            redacted=True,
            reason=f"key '{key}' looks sensitive",
        )

    if _URL_PATTERN.match(text) and "@" in text.split("://", 1)[1]:
        return SanitizedValue(
            value=sanitize_url(text),
            redacted=True,
            reason="value carried credentials",
        )

    return SanitizedValue(value=text, redacted=False)


def sanitize_url(url: str) -> str:
    """Strip credentials, query and fragment from a url, keeping its origin."""

    match = _URL_PATTERN.match(url)

    if not match:
        return url

    scheme = match.group("scheme").lower()
    rest = match.group("rest")

    # Drop the userinfo segment entirely rather than masking it.
    if "@" in rest:
        rest = rest.split("@", 1)[1]

    # Keep only the authority (host[:port]); paths and queries often carry
    # tokens or identifiers that are not needed for the analysed structure.
    authority = rest.split("/", 1)[0]

    return f"{scheme}://{authority}"


def extract_endpoint_candidate(value: object) -> EndpointCandidate | None:
    """Find a network endpoint inside a configuration value, if there is one.

    Handles `scheme://host:port`, bare `host:port` and image-style references are
    deliberately ignored. Credentials are never carried into the result.
    """

    if not isinstance(value, str):
        return None

    text = value.strip()

    if not text:
        return None

    url_match = _URL_PATTERN.match(text)

    if url_match:
        scheme = url_match.group("scheme").lower()
        rest = url_match.group("rest")

        if "@" in rest:
            return None

        authority = rest.split("/", 1)[0].split("?", 1)[0]

        if not authority:
            return None

        host_port = _HOST_PORT_PATTERN.match(authority)

        if host_port:
            return EndpointCandidate(
                host=host_port.group("host").lower(),
                port=int(host_port.group("port")),
                scheme=scheme,
                sanitized_value=f"{scheme}://{authority}",
            )

        return EndpointCandidate(
            host=authority.lower(),
            port=DEFAULT_PORTS_BY_SCHEME.get(scheme),
            scheme=scheme,
            sanitized_value=f"{scheme}://{authority}",
        )

    host_port = _HOST_PORT_PATTERN.match(text)

    if host_port:
        return EndpointCandidate(
            host=host_port.group("host").lower(),
            port=int(host_port.group("port")),
            sanitized_value=text,
        )

    return None


def parse_compose_port(entry: object) -> dict | None:
    """Parse a Compose port entry into its parts.

    Handles both the short string form (`"8080:80"`, `"127.0.0.1:8080:80/udp"`)
    and the long mapping form (`{published: 8080, target: 80}`).
    """

    if isinstance(entry, dict):
        published = entry.get("published")
        target = entry.get("target")

        return {
            "host_ip": entry.get("host_ip"),
            "host_port": _as_int_or_text(published),
            "container_port": _as_int_or_text(target),
            "protocol": (entry.get("protocol") or "tcp"),
            "raw": None,
        }

    if not isinstance(entry, (str, int)):
        return None

    text = str(entry).strip()
    match = _COMPOSE_PORT_PATTERN.match(text)

    if not match:
        return None

    return {
        "host_ip": match.group("host_ip"),
        "host_port": match.group("host_port"),
        "container_port": match.group("container_port"),
        "protocol": (match.group("protocol") or "tcp").lower(),
        "raw": text,
    }


def _as_int_or_text(value: object) -> int | str | None:
    """Coerce a port value to an int when it is numeric, else keep the text."""

    if value is None:
        return None

    if isinstance(value, int):
        return value

    text = str(value)

    return int(text) if text.isdigit() else text


def port_number(value: object) -> int | None:
    """Return a single numeric port, or None for a range or non-numeric value."""

    if isinstance(value, int):
        return value

    if isinstance(value, str) and value.isdigit():
        return int(value)

    # A range (`8000-8010`) has no single port to record.
    return None
