# Tests for the run manifest builder

import datetime as dt
import hashlib
import platform

import pytest

from app.components.degradation_scoring.reporting import manifest
from app.components.degradation_scoring.reporting.manifest import (
    KEY_PACKAGES,
    build_manifest,
    file_hash,
    package_versions,
)


def test_file_hash_is_sha256_of_the_bytes() -> None:
    assert file_hash(b"abc") == "sha256:" + hashlib.sha256(b"abc").hexdigest()


def test_package_versions_lists_every_key_package() -> None:
    versions = package_versions()

    assert list(versions) == list(KEY_PACKAGES)
    assert versions["pydantic"]
    assert versions["networkx"]


def test_missing_package_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manifest, "KEY_PACKAGES", ("no-such-package-c4",))

    assert manifest.package_versions() == {"no-such-package-c4": None}


def test_manifest_keeps_the_facts_and_adds_environment_and_hashes() -> None:
    created = dt.datetime(
        2026, 10, 18, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30))
    )
    result = build_manifest(
        {"run_id": "r1", "counts": {"ranked": 2}}, {"b.json": b"2", "a.json": b"1"}, created
    )

    assert list(result)[:2] == ["run_id", "counts"]
    assert result["created_at"] == "2026-10-18T06:30:00+00:00"
    assert result["python"] == platform.python_version()
    assert list(result["outputs"]) == ["a.json", "b.json"]
    assert result["outputs"]["a.json"] == file_hash(b"1")
