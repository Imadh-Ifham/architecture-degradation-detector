"""Decisions reconstructed from a repository's own configuration.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    The source that exists because most repositories hold no decision records
    at all. About one in twenty does, and a validator that needs them cannot
    run on the other nineteen.

    The finding worth defending: for *structural* rules, executable
    configuration is stronger evidence than a prose decision record. A network
    policy admitting exactly one peer is unambiguous, versioned, current and
    actually enforced at run time; a paragraph saying the same thing is none
    of those four. Prose remains the better source for *why* a rule exists,
    which is why a declared record still outranks a reconstructed one when
    both speak about the same relationship.

    Three extractors, all reading documents handed over by the reader:

      network policies  -> may_call, and the default-deny that makes the
                           absence of a permission mean something
      service contracts -> declared_rpc, the operations a service exposes
      identity manifests-> must_call_via, where a workload's identity is
                           declared

    The default-deny is emitted once, as a rule about every pair, rather than
    expanded into one refusal per unpermitted pair. Twelve elements would make
    116 of those, all saying the same thing, and the resolver can reach the
    same answer by preferring a specific permission over the general refusal.

    The third extractor is the one whose constraint fits loosely. "A workload
    obtains its identity through the shared component" is not quite "A reaches
    B only through C", and the vocabulary is closed on purpose, so it is
    recorded under the nearest kind with the reason in its rationale rather
    than given a fifth constraint of its own.
"""

import re

import yaml

from ...models import (
    ConstraintKind,
    DecisionRecord,
    EvidenceStrength,
    ExtractionMethod,
    SourceTier,
)
from ...ports import SourceArtifactReader
from .base import (
    DecisionSourceError,
    SourceOutcome,
    SourceRequest,
    decision_record,
)

CONTRACT_PATTERN = "**/*.proto"

WORKLOAD_KINDS = frozenset({"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"})

_SERVICE_BLOCK = re.compile(r"^service\s+(\w+)\s*\{", re.MULTILINE)
_RPC = re.compile(r"^\s*rpc\s+(\w+)\s*\(", re.MULTILINE)


class ConfigurationScan:
    """Rules reconstructed from the code repository's deployment configuration."""

    name = "config_scan"

    def __init__(self, reader: SourceArtifactReader) -> None:
        self._reader = reader

    def collect(self, request: SourceRequest) -> SourceOutcome:
        """Reconstruct every rule this release's configuration states."""

        documents = self._manifest_documents(request)

        records = (
            self._communication_rules(documents, request)
            + self._identity_rules(documents, request)
            + self._contract_rules(request)
        )

        reason = None
        if not records:
            reason = "no policies, contracts or identity manifests in this release"

        return SourceOutcome(
            source=self.name, ran=True, records=tuple(records), reason=reason
        )

    def _manifest_documents(self, request: SourceRequest) -> list[tuple[str, dict]]:
        """Every YAML document in the release's manifests, with its path.

        One manifest file can hold several documents, and the identity rule
        turns on whether a ServiceAccount shares a file with a workload - so
        the path travels with each document rather than being resolved later.
        """

        documents: list[tuple[str, dict]] = []
        for path in sorted(request.manifest_paths):
            text = self._reader.read_text(
                request.code_repository_id, request.release_id, path
            )
            try:
                loaded = list(yaml.safe_load_all(text))
            except yaml.YAMLError as error:
                raise DecisionSourceError(
                    f"'{path}' is not readable YAML, so this release cannot be "
                    "scanned. A document that will not parse looks exactly like "
                    "a rule that was withdrawn."
                ) from error

            documents.extend(
                (path, document) for document in loaded if isinstance(document, dict)
            )
        return documents

    def _communication_rules(
        self, documents: list[tuple[str, dict]], request: SourceRequest
    ) -> list[DecisionRecord]:
        """Permissions and the default refusal, from the network policies."""

        records: list[DecisionRecord] = []
        permitted: set[tuple[str, str]] = set()

        for path, document in documents:
            if document.get("kind") != "NetworkPolicy":
                continue

            specification = document.get("spec") or {}
            selected = _selected_app(specification.get("podSelector"))

            if selected is None:
                if not specification.get("ingress") and not specification.get("egress"):
                    records.append(
                        decision_record(
                            request,
                            decision_id="np-deny-all",
                            subject="*",
                            constraint=ConstraintKind.MUST_NOT_CALL,
                            object_="*",
                            source=self.name,
                            source_repository=request.code_repository_id,
                            source_ref=path,
                            source_tier=SourceTier.EXECUTABLE_CONFIG,
                            source_strength=EvidenceStrength.AUTHORITATIVE,
                            extraction_method=ExtractionMethod.RECONSTRUCTED,
                            rationale=(
                                "A policy selecting every pod and permitting "
                                "nothing denies any traffic no other policy allows."
                            ),
                        )
                    )
                continue

            for caller, callee in _permitted_pairs(specification, selected):
                if (caller, callee) in permitted:
                    # The same permission can be written twice - as what the
                    # callee admits and as what the caller is allowed to reach.
                    # One rule, so one record, and the first file wins because
                    # the paths are walked in order.
                    continue
                permitted.add((caller, callee))
                records.append(
                    decision_record(
                        request,
                        decision_id=f"rule-{caller}-{callee}",
                        subject=caller,
                        constraint=ConstraintKind.MAY_CALL,
                        object_=callee,
                        source=self.name,
                        source_repository=request.code_repository_id,
                        source_ref=path,
                        source_tier=SourceTier.EXECUTABLE_CONFIG,
                        source_strength=EvidenceStrength.AUTHORITATIVE,
                        extraction_method=ExtractionMethod.RECONSTRUCTED,
                    )
                )

        return records

    def _identity_rules(
        self, documents: list[tuple[str, dict]], request: SourceRequest
    ) -> list[DecisionRecord]:
        """Where workload identity is declared, which is an architectural choice.

        Two shapes occur and they are a genuine decision apart: identity
        manifests gathered into one shared overlay, or an identity declared in
        the same file as the workload that uses it. A team that moves from the
        first to the second has changed how identity is granted, and this is
        the record that lets that change be seen.
        """

        accounts = [
            (path, document)
            for path, document in documents
            if document.get("kind") == "ServiceAccount"
        ]
        if not accounts:
            return []

        with_workload = {
            path
            for path, document in documents
            if document.get("kind") in WORKLOAD_KINDS
        }

        records: list[DecisionRecord] = []
        shared = sorted(
            {_directory(path) for path, _ in accounts if path not in with_workload}
        )
        inline = sorted({path for path, _ in accounts if path in with_workload})

        for directory in shared:
            records.append(
                decision_record(
                    request,
                    decision_id="sa-shared-component",
                    subject="*",
                    constraint=ConstraintKind.MUST_CALL_VIA,
                    object_=directory,
                    source=self.name,
                    source_repository=request.code_repository_id,
                    source_ref=directory,
                    source_tier=SourceTier.EXECUTABLE_CONFIG,
                    source_strength=EvidenceStrength.AUTHORITATIVE,
                    extraction_method=ExtractionMethod.RECONSTRUCTED,
                    rationale=(
                        "Workload identity is declared in one shared, opt-in "
                        "overlay rather than beside each workload."
                    ),
                )
            )

        if inline:
            records.append(
                decision_record(
                    request,
                    decision_id="sa-inline-with-workload",
                    subject="*",
                    constraint=ConstraintKind.MUST_CALL_VIA,
                    object_="inline ServiceAccount beside the workload",
                    source=self.name,
                    source_repository=request.code_repository_id,
                    source_ref=inline[0],
                    source_tier=SourceTier.EXECUTABLE_CONFIG,
                    source_strength=EvidenceStrength.AUTHORITATIVE,
                    extraction_method=ExtractionMethod.RECONSTRUCTED,
                    rationale=(
                        "A workload declares its own identity in the same "
                        "manifest as the workload itself."
                    ),
                )
            )

        return records

    def _contract_rules(self, request: SourceRequest) -> list[DecisionRecord]:
        """The operations each service declares, from its contract files.

        Searched for rather than taken from the architecture: recovery
        classifies deployment manifests, and a service contract is not one.

        Read with a regular expression rather than a protobuf compiler. The
        question is which service declares which operation, which is two lines
        of the grammar - and a compiler would be a dependency, a build step
        and a toolchain version for a reader of two lines.
        """

        records: list[DecisionRecord] = []
        for path in self._reader.list_paths(
            request.code_repository_id, request.release_id, CONTRACT_PATTERN
        ):
            text = self._reader.read_text(
                request.code_repository_id, request.release_id, path
            )
            for service, body in _service_blocks(text):
                for operation in _RPC.findall(body):
                    records.append(
                        decision_record(
                            request,
                            decision_id=f"rpc-{service.lower()}-{operation.lower()}",
                            subject=service,
                            constraint=ConstraintKind.DECLARED_RPC,
                            object_=operation,
                            source=self.name,
                            source_repository=request.code_repository_id,
                            source_ref=path,
                            source_tier=SourceTier.EXECUTABLE_CONFIG,
                            source_strength=EvidenceStrength.AUTHORITATIVE,
                            extraction_method=ExtractionMethod.RECONSTRUCTED,
                        )
                    )
        return records


def _selected_app(selector: dict | None) -> str | None:
    """The app a policy's podSelector selects, or None when it selects all."""

    labels = (selector or {}).get("matchLabels") or {}
    return labels.get("app")


def _permitted_pairs(specification: dict, selected: str) -> list[tuple[str, str]]:
    """Every caller-callee pair this policy permits.

    A policy is written from the selected workload's side, so an ingress peer
    is a caller and an egress peer is a callee. Getting that round the wrong
    way would invert every rule in the corpus and still look plausible.
    """

    pairs = []
    for rule in specification.get("ingress") or ():
        for peer in (rule or {}).get("from") or ():
            caller = _selected_app((peer or {}).get("podSelector"))
            if caller:
                pairs.append((caller, selected))

    for rule in specification.get("egress") or ():
        for peer in (rule or {}).get("to") or ():
            callee = _selected_app((peer or {}).get("podSelector"))
            if callee:
                pairs.append((selected, callee))

    return pairs


def _service_blocks(text: str) -> list[tuple[str, str]]:
    """Each `service X { ... }` block in a contract, as a name and a body.

    The closing brace is found by counting depth rather than by searching for
    the next one. An operation is written `rpc Name(Request) returns (Reply)
    {}`, so the first closing brace after the block opens belongs to the first
    operation - and a reader that stops there sees one operation per service
    and reports a contract surface far smaller than the real one.
    """

    blocks = []
    for match in _SERVICE_BLOCK.finditer(text):
        depth = 1
        for index in range(match.end(), len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append((match.group(1), text[match.end() : index]))
                    break
    return blocks


def _directory(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


__all__ = ["ConfigurationScan"]
