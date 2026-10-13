"""Targeted manifest inspection.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Reads a bounded subset of a repository: only files already classified as
    build or deployment manifests, and only up to a size cap. This is the one
    place the inventory looks inside a file, because a manifest's declared name
    is the difference between a confirmed component and a guessed one.

    No other file is opened. Parsing failures degrade to a warning and leave
    the file's classification untouched.
"""

import json
import re
import tomllib
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.components.architecture_recovery.repository_inventory.models import (
    FileCategory,
    FileRecord,
)


# Kubernetes object kinds that represent a deployable workload or endpoint.
# Bare Pods are excluded: they are usually local debugging artifacts.
WORKLOAD_KINDS: frozenset[str] = frozenset(
    {
        "deployment",
        "statefulset",
        "daemonset",
        "replicaset",
        "service",
        "job",
        "cronjob",
        "rollout",
        "deploymentconfig",
    }
)

_JSON_NAME_MANIFESTS: frozenset[str] = frozenset(
    {"package.json", "composer.json", "deno.json", "deno.jsonc"}
)
_CSPROJ_SUFFIXES: tuple[str, ...] = (".csproj", ".fsproj", ".vbproj")

_GO_MODULE = re.compile(r"^module\s+(\S+)", re.MULTILINE)
_GRADLE_PROJECT_NAME = re.compile(r"""rootProject\.name\s*=\s*['"]([^'"]+)['"]""")
_SBT_NAME = re.compile(r'name\s*:=\s*"([^"]+)"')
_MIX_APP = re.compile(r"app:\s*:([A-Za-z0-9_]+)")
_CLOJURE_PROJECT = re.compile(r"\(defproject\s+([^\s)]+)")


@dataclass(frozen=True)
class ManifestAnalysis:
    """What a single manifest file revealed.

    `declared_name` is a build unit's own name; `service_names` are services a
    deployment manifest declares. Both are empty when nothing could be read.
    """

    path: str
    declared_name: str | None = None
    service_names: tuple[str, ...] = ()
    warning: str | None = None


class ManifestReader:
    """Reads build and deployment manifests to extract declared names."""

    def __init__(self, max_bytes: int = 262_144) -> None:
        """Store the maximum number of bytes read from any single manifest."""

        self._max_bytes = max_bytes

    def analyse(self, file: FileRecord, absolute_path: Path) -> ManifestAnalysis:
        """Extract declared names from one manifest file.

        Never raises: an unreadable or malformed manifest yields an analysis
        carrying a warning.
        """

        try:
            raw = self._read_bytes(absolute_path)
        except OSError as error:
            return ManifestAnalysis(
                path=file.path,
                warning=f"could not read '{file.path}': {error}",
            )

        if raw is None:
            return ManifestAnalysis(
                path=file.path,
                warning=(
                    f"skipped '{file.path}': larger than the "
                    f"{self._max_bytes} byte manifest limit"
                ),
            )

        text = raw.decode("utf-8", errors="replace")

        try:
            if file.category is FileCategory.BUILD_MANIFEST:
                return ManifestAnalysis(
                    path=file.path,
                    declared_name=self._declared_name(file.name.lower(), text),
                )

            if file.category is FileCategory.DEPLOYMENT_MANIFEST:
                if file.format == "yaml" and "{{" in text:
                    # Helm-style templates are not valid YAML; resolving them
                    # needs a template engine, which is out of scope here.
                    return ManifestAnalysis(
                        path=file.path,
                        warning=(
                            f"skipped '{file.path}': templated manifest cannot be "
                            "parsed without resolving its template expressions"
                        ),
                    )

                return ManifestAnalysis(
                    path=file.path,
                    service_names=self._service_names(
                        file.name.lower(), file.format, text
                    ),
                )
        except (ValueError, yaml.YAMLError, ElementTree.ParseError) as error:
            # Malformed content is a data problem, not a fatal error.
            return ManifestAnalysis(
                path=file.path,
                warning=f"could not parse '{file.path}': {error}",
            )

        return ManifestAnalysis(path=file.path)

    def _read_bytes(self, path: Path) -> bytes | None:
        """Read at most the size cap, returning None when the file exceeds it."""

        with path.open("rb") as handle:
            raw = handle.read(self._max_bytes + 1)

        return None if len(raw) > self._max_bytes else raw

    # ------------------------------------------------------------------ #
    # Build manifests: the unit's own declared name
    # ------------------------------------------------------------------ #

    def _declared_name(self, name: str, text: str) -> str | None:
        """Return the name a build manifest declares for its unit."""

        if name == "go.mod":
            return self._first_group(_GO_MODULE, text)

        if name in _JSON_NAME_MANIFESTS:
            return self._json_field(text, ("name",))

        if name == "pyproject.toml":
            data = tomllib.loads(text)
            # Layout differs between PEP 621, Poetry and PDM.
            for section in (
                data.get("project"),
                (data.get("tool") or {}).get("poetry"),
                (data.get("tool") or {}).get("pdm"),
            ):
                if isinstance(section, dict) and section.get("name"):
                    return str(section["name"])
            return None

        if name == "cargo.toml":
            package = tomllib.loads(text).get("package")
            if isinstance(package, dict) and package.get("name"):
                return str(package["name"])
            return None

        if name == "pom.xml":
            return self._xml_element_text(text, ("artifactId",))

        if name.endswith(_CSPROJ_SUFFIXES):
            return self._xml_element_text(text, ("AssemblyName", "RootNamespace"))

        if name.startswith(("build.gradle", "settings.gradle")):
            return self._first_group(_GRADLE_PROJECT_NAME, text)

        if name == "build.sbt":
            return self._first_group(_SBT_NAME, text)

        if name == "mix.exs":
            return self._first_group(_MIX_APP, text)

        if name == "project.clj":
            return self._first_group(_CLOJURE_PROJECT, text)

        if name in {"pubspec.yaml", "pubspec.yml", "chart.yaml"}:
            data = yaml.safe_load(text)
            if isinstance(data, dict) and data.get("name"):
                return str(data["name"])
            return None

        return None

    # ------------------------------------------------------------------ #
    # Deployment manifests: the services they declare
    # ------------------------------------------------------------------ #

    def _service_names(
        self, name: str, file_format: str | None, text: str
    ) -> tuple[str, ...]:
        """Return the service names a deployment manifest declares."""

        if name == "procfile":
            # A Procfile declares one process type per line: `web: cmd`.
            return tuple(
                line.split(":", 1)[0].strip()
                for line in text.splitlines()
                if ":" in line and not line.strip().startswith("#")
            )

        # Only declarative YAML manifests (Compose, Kubernetes, Helm) carry
        # service names. A Dockerfile is a build recipe, not YAML, so parsing
        # it would only produce noise.
        if file_format != "yaml":
            return ()

        documents = [doc for doc in yaml.safe_load_all(text) if doc is not None]

        services: list[str] = []

        for document in documents:
            if not isinstance(document, dict):
                continue

            # Compose-style: a top level `services` mapping of service names.
            compose_services = document.get("services")
            if isinstance(compose_services, dict):
                services.extend(str(key) for key in compose_services)

            # Kubernetes-style: `kind` plus `metadata.name`.
            kind = str(document.get("kind", "")).lower()
            metadata = document.get("metadata")

            if kind in WORKLOAD_KINDS and isinstance(metadata, dict):
                declared = metadata.get("name")
                if declared:
                    services.append(str(declared))

        # De-duplicate while preserving document order.
        seen: dict[str, None] = {}
        for service in services:
            if service:
                seen.setdefault(service, None)

        return tuple(seen)

    # ------------------------------------------------------------------ #
    # Small parsing helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _first_group(pattern: re.Pattern[str], text: str) -> str | None:
        """Return the first capture group of `pattern`, or None."""

        match = pattern.search(text)
        return match.group(1).strip() if match else None

    @staticmethod
    def _json_field(text: str, keys: tuple[str, ...]) -> str | None:
        """Return the first present top-level JSON string field."""

        data = json.loads(text)

        if not isinstance(data, dict):
            return None

        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value:
                return value

        return None

    @staticmethod
    def _xml_element_text(text: str, tags: tuple[str, ...]) -> str | None:
        """Return the text of the first element matching any local tag name.

        Maven and MSBuild documents are namespaced, so elements are matched on
        their local name rather than a fully qualified one.
        """

        root = ElementTree.fromstring(text)

        for element in root.iter():
            local_name = element.tag.rsplit("}", 1)[-1]
            if local_name in tags and element.text and element.text.strip():
                return element.text.strip()

        return None
