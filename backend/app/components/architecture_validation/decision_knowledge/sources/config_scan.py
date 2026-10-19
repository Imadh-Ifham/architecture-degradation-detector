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

    **One unreadable manifest is skipped and named; all of them is fatal.**
    Recovery classifies anything that looks like configuration, so a
    repository is free to contain a fixture with a yaml-ish name that was
    never a rule - and refusing the whole release over one of those makes the
    component unusable on repositories that have one. A release where nothing
    parses is the other claim entirely: "no rules here" would then be
    indistinguishable from a release whose rules were all withdrawn, which is
    the confusion this check exists to prevent.

    The third extractor is the one whose constraint fits loosely. "A workload
    obtains its identity through the shared component" is not quite "A reaches
    B only through C", and the vocabulary is closed on purpose, so it is
    recorded under the nearest kind with the reason in its rationale rather
    than given a fifth constraint of its own.
"""

import re
from dataclasses import dataclass

import yaml

from ...models import (
    ConstraintKind,
    DecisionRecord,
    EvidenceStrength,
    ExtractionMethod,
    SourceTier,
    Span,
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

        documents, unreadable = self._manifest_documents(request)

        records = (
            self._communication_rules(documents, request)
            + self._identity_rules(documents, request)
            + self._contract_rules(request)
        )

        reason = None
        if not records:
            reason = "no policies, contracts or identity manifests in this release"

        if unreadable:
            # Named rather than counted. "3 files were skipped" sends somebody
            # looking; the paths tell them where, and whether any of them was
            # a file that should have held a rule.
            listed = ", ".join(f"'{path}'" for path in unreadable[:3])
            more = f" and {len(unreadable) - 3} more" if len(unreadable) > 3 else ""
            skipped = (
                f"{len(unreadable)} manifest(s) are not readable YAML and were "
                f"skipped: {listed}{more}"
            )
            reason = f"{reason}; {skipped}" if reason else skipped

        return SourceOutcome(
            source=self.name, ran=True, records=tuple(records), reason=reason
        )

    def _manifest_documents(
        self, request: SourceRequest
    ) -> tuple[list["_Document"], list[str]]:
        """Every YAML document in the release's manifests, with its path.

        One manifest file can hold several documents, and the identity rule
        turns on whether a ServiceAccount shares a file with a workload - so
        the path travels with each document rather than being resolved later.
        """

        documents: list[_Document] = []
        unreadable: list[str] = []

        for path in sorted(request.manifest_paths):
            text = self._reader.read_text(
                request.code_repository_id, request.release_id, path
            )
            try:
                loaded = list(yaml.safe_load_all(text))
                composed = list(yaml.compose_all(text))
            except yaml.YAMLError:
                unreadable.append(path)
                continue

            for data, node in zip(loaded, composed):
                if isinstance(data, dict):
                    documents.append(_located(path, data, node))

        # Every manifest failing is a different claim from one failing. One
        # unreadable file is a file - recovery classifies anything that looks
        # like configuration, and a repository is free to contain a fixture
        # with a yaml-ish name that was never a rule. All of them unreadable
        # means the release cannot be read at all, and reporting "no rules"
        # for it would be indistinguishable from a release that states none.
        if request.manifest_paths and not documents and unreadable:
            raise DecisionSourceError(
                f"none of this release's {len(unreadable)} manifests are "
                "readable YAML, so it cannot be scanned. A release that will "
                "not parse looks exactly like one whose rules were withdrawn."
            )

        return documents, unreadable

    def _communication_rules(
        self, documents: list["_Document"], request: SourceRequest
    ) -> list[DecisionRecord]:
        """Permissions and the default refusal, from the network policies."""

        records: list[DecisionRecord] = []
        permitted: set[tuple[str, str]] = set()

        for located in documents:
            path, document = located.path, located.data
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
                            source_span=located.span(),
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
                # The policy is written from `selected`'s side, so the entry
                # that created this rule is the other end of the pair - and
                # that entry's line is what a reader has to be shown.
                peer = callee if caller == selected else caller
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
                        source_span=located.line_of(peer),
                        source_tier=SourceTier.EXECUTABLE_CONFIG,
                        source_strength=EvidenceStrength.AUTHORITATIVE,
                        extraction_method=ExtractionMethod.RECONSTRUCTED,
                    )
                )

        return records

    def _identity_rules(
        self, documents: list["_Document"], request: SourceRequest
    ) -> list[DecisionRecord]:
        """Where workload identity is declared, which is an architectural choice.

        Two shapes occur and they are a genuine decision apart: identity
        manifests gathered into one shared overlay, or an identity declared in
        the same file as the workload that uses it. A team that moves from the
        first to the second has changed how identity is granted, and this is
        the record that lets that change be seen.
        """

        accounts = [
            located for located in documents if located.data.get("kind") == "ServiceAccount"
        ]
        if not accounts:
            return []

        with_workload = {
            located.path
            for located in documents
            if located.data.get("kind") in WORKLOAD_KINDS
        }

        records: list[DecisionRecord] = []
        shared = sorted(
            {_directory(a.path) for a in accounts if a.path not in with_workload}
        )
        inline = sorted(
            [a for a in accounts if a.path in with_workload], key=lambda a: a.path
        )

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
                    source_span=None,
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
                    source_ref=inline[0].path,
                    source_span=inline[0].span(),
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
            for service, body, offset in _service_blocks(text):
                for match in _RPC.finditer(body):
                    operation = match.group(1)
                    line = _line_at(text, offset + match.start(1))
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
                            source_span=Span(
                                path=path, start_line=line, end_line=line
                            ),
                            source_tier=SourceTier.EXECUTABLE_CONFIG,
                            source_strength=EvidenceStrength.AUTHORITATIVE,
                            extraction_method=ExtractionMethod.RECONSTRUCTED,
                        )
                    )
        return records


@dataclass(frozen=True)
class _Document:
    """One YAML document, with the lines its parser said things were on.

    The data comes from `safe_load_all` and the line numbers from
    `compose_all` over the same text - one parser, used twice, rather than a
    second reader that could disagree about what the document says. Evidence
    retrieval quotes these lines, and only whatever parsed the file knows
    them.
    """

    path: str
    data: dict
    app_lines: dict[str, int]
    first_line: int
    last_line: int

    def span(self) -> Span:
        """The whole document, for a rule that is about all of it."""

        return Span(
            path=self.path, start_line=self.first_line, end_line=self.last_line
        )

    def line_of(self, app: str) -> Span | None:
        """The entry where one workload is named."""

        line = self.app_lines.get(app)
        return Span(path=self.path, start_line=line, end_line=line) if line else None


def _located(path: str, data: dict, node) -> _Document:
    return _Document(
        path=path,
        data=data,
        app_lines=_app_lines(node),
        first_line=node.start_mark.line + 1,
        last_line=_last_line(node),
    )


def _last_line(node) -> int:
    """The last line a document actually occupies.

    A document's end mark sits at the start of whatever follows it, so taking
    it as a line number points one line past the end - and a span that names a
    line the file does not have cannot be quoted.
    """

    end = node.end_mark
    return end.line if end.column == 0 and end.line > node.start_mark.line else end.line + 1


def _app_lines(node) -> dict[str, int]:
    """Where each `app:` value sits, taken from the parser's own marks.

    The last occurrence of a name wins. A policy names its own workload first,
    in the selector, and the peers it admits after it - and the peer entry is
    the one a permission is read from.
    """

    found: dict[str, int] = {}

    def visit(current) -> None:
        if isinstance(current, yaml.MappingNode):
            for key, value in current.value:
                if getattr(key, "value", None) == "app" and isinstance(
                    value, yaml.ScalarNode
                ):
                    found[value.value] = value.start_mark.line + 1
                visit(value)
        elif isinstance(current, yaml.SequenceNode):
            for item in current.value:
                visit(item)

    visit(node)
    return found


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


def _service_blocks(text: str) -> list[tuple[str, str, int]]:
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
                    blocks.append(
                        (match.group(1), text[match.end() : index], match.end())
                    )
                    break
    return blocks


def _line_at(text: str, offset: int) -> int:
    """The 1-based line an offset falls on.

    The contract reader works with a regular expression rather than a parser,
    so it has an offset where the YAML reader has a mark. Same answer, counted
    rather than reported.
    """

    return text.count("\n", 0, offset) + 1


def _directory(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


__all__ = ["ConfigurationScan"]
