# Run manifest: everything needed to regenerate a run's numbers: the run facts
# from the pipeline, plus when it ran, the Python and package versions, and output file hashes.

import datetime as dt
import hashlib
import platform
from collections.abc import Mapping
from importlib import metadata
from typing import Any

KEY_PACKAGES = (
    "jinja2",
    "networkx",
    "numpy",
    "pathspec",
    "pydantic",
    "pydriller",
    "pymcdm",
    "scipy",
    "structlog",
)


def package_versions() -> dict[str, str | None]:
    # installed version of each key package, None when it is missing
    versions: dict[str, str | None] = {}
    for name in KEY_PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def file_hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def build_manifest(
    facts: Mapping[str, Any], outputs: Mapping[str, bytes], created_at: dt.datetime
) -> dict[str, Any]:
    # run facts first, then the environment and the hash of every other output file
    return {
        **facts,
        "created_at": created_at.astimezone(dt.UTC).isoformat(),
        "python": platform.python_version(),
        "packages": package_versions(),
        "outputs": {name: file_hash(data) for name, data in sorted(outputs.items())},
    }
