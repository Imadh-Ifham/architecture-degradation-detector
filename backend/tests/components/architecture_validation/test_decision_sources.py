"""Decision source tests: where the rules come from, and what they say.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    Covers the three places architectural decisions can be found, against the
    subject working trees for both releases.

    Two of these carry more weight than the rest. `test_tier_one_runs_and_
    finds_nothing` is the research finding stated as an assertion rather than
    as a claim - the repository keeps no decision records, and the adapter
    that establishes that has to be seen to run. And the direction tests in
    `TestPermissionDirection` guard the one mistake that would invert the
    whole corpus while still looking plausible: a policy is written from the
    receiving workload's side, so an admitted peer is a caller.

    The counts here were checked by hand against the committed manifests
    before the scan was written, which is why they are written as literals.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from app.components.architecture_validation.decision_knowledge import (
    DecisionKnowledgeService,
    DecisionSourceError,
    SourceRequest,
)
from app.components.architecture_validation.decision_knowledge.sources import (
    ConfigurationScan,
    ExternalDecisionRecords,
    RepositoryDecisionRecords,
    registered_modes,
    sources_for,
)
from app.components.architecture_validation.models import (
    ConstraintKind,
    EvidenceStrength,
    ExtractionMethod,
    SourceTier,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "validation"
SUBJECT = FIXTURES / "subject"
SNAPSHOTS = Path(__file__).resolve().parents[3] / "data" / "snapshots"

RELEASES = ("v0.9.0", "v0.10.0")
EXTRACTED_AT = datetime(2026, 10, 15)

PERMITTED_PAIRS = 16
"""Permissions in the policy set, counted by hand from the 14 documents."""

DECLARED_OPERATIONS = 7
"""Operations across the four services the contract declares."""


class WorkspaceReader:
    """Reads the generated subject tree in place of an ingested checkout."""

    def read_text(self, repository_id, release_id, path):
        return (SUBJECT / release_id / path).read_text(encoding="utf-8")

    def list_paths(self, repository_id, release_id, pattern):
        root = SUBJECT / release_id
        return sorted(
            str(match.relative_to(root)).replace("\\", "/")
            for match in root.glob(pattern)
            if match.is_file()
        )


class DictReader:
    """A repository that is a dict, for the cases a real tree cannot show."""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    def read_text(self, repository_id, release_id, path):
        return self.files[path]

    def list_paths(self, repository_id, release_id, pattern):
        from fnmatch import fnmatch

        return sorted(path for path in self.files if fnmatch(path, pattern))


def manifest_paths(release: str) -> tuple[str, ...]:
    """The manifests recovery located for a release, as the scan receives them."""

    snapshot = json.loads(
        (SNAPSHOTS / f"snapshot_{release}.json").read_text(encoding="utf-8")
    )
    return tuple(snapshot["manifest_paths"])


def request_for(release: str, **overrides) -> SourceRequest:
    return SourceRequest(
        code_repository_id="online-boutique",
        release_id=release,
        extracted_at=EXTRACTED_AT,
        manifest_paths=manifest_paths(release),
        **overrides,
    )


def scan(release: str, reader=None):
    return ConfigurationScan(reader or WorkspaceReader()).collect(request_for(release))


class TestTheConfigurationScan:
    """What the repository's own configuration says, read back as decisions."""

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_permitted_pair_and_the_one_default_deny(self, release):
        """Checkable by hand: 14 policy documents, one denying everything and
        thirteen listing the peers they admit."""

        records = scan(release).records

        permitted = [r for r in records if r.constraint is ConstraintKind.MAY_CALL]
        refused = [r for r in records if r.constraint is ConstraintKind.MUST_NOT_CALL]

        assert len(permitted) == PERMITTED_PAIRS
        assert len(refused) == 1
        assert refused[0].subject == "*" and refused[0].object == "*"

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_contract_surface_is_every_operation_not_one_per_service(self, release):
        """An operation is written `rpc Name(In) returns (Out) {}`, so a reader
        that stops at the first closing brace finds one per service and
        under-reports the declared surface by more than half."""

        declared = [
            r
            for r in scan(release).records
            if r.constraint is ConstraintKind.DECLARED_RPC
        ]

        assert len(declared) == DECLARED_OPERATIONS
        assert len({r.subject for r in declared}) == 4

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_record_can_be_pointed_at(self, release):
        """A record whose source cannot be shown to an architect is not
        evidence, so the reference has to resolve to something that exists."""

        for record in scan(release).records:
            located = SUBJECT / release / record.source_ref
            assert located.exists(), record.source_ref
            assert record.source_tier is SourceTier.EXECUTABLE_CONFIG
            assert record.extraction_method is ExtractionMethod.RECONSTRUCTED
            assert record.extracted_at == EXTRACTED_AT

    @pytest.mark.parametrize("release", RELEASES)
    def test_a_rule_can_name_something_recovery_never_observed(self, release):
        """A permission for a dependency that does not happen. It is a finding
        about the architecture rather than a fault in the scan, so it is kept
        and counted rather than filtered out."""

        permitted = {
            (r.subject, r.object)
            for r in scan(release).records
            if r.constraint is ConstraintKind.MAY_CALL
        }

        assert ("cartservice", "redis") in permitted

    @pytest.mark.parametrize("release", RELEASES)
    def test_two_scans_of_one_release_are_identical(self, release):
        """Re-running a failed validation re-runs the scan, and the published
        graph has to come out byte-identical."""

        assert scan(release).records == scan(release).records

    def test_a_release_where_nothing_parses_raises(self):
        """Absence closes a validity interval, so a release silently read as
        holding no rules would read as every rule having been withdrawn."""

        reader = DictReader({"kustomize/broken.yaml": "kind: [unclosed\n"})
        request = SourceRequest(
            code_repository_id="online-boutique",
            release_id="v0.10.0",
            extracted_at=EXTRACTED_AT,
            manifest_paths=("kustomize/broken.yaml",),
        )

        with pytest.raises(DecisionSourceError, match="readable YAML"):
            ConfigurationScan(reader).collect(request)

    def test_one_document_that_will_not_parse_is_skipped_and_named(self):
        """Recovery classifies anything that looks like configuration, so a
        repository is free to hold a fixture with a yaml-ish name that was
        never a rule. Refusing the whole release over one of those makes the
        component unusable on repositories that have one - and the subject
        system has one.

        It is named rather than counted: "a file was skipped" sends somebody
        looking, and the path tells them whether it was one that should have
        held a rule."""

        policy = yaml.safe_dump(
            {
                "kind": "NetworkPolicy",
                "metadata": {"name": "b"},
                "spec": {
                    "podSelector": {"matchLabels": {"app": "b"}},
                    "ingress": [
                        {"from": [{"podSelector": {"matchLabels": {"app": "a"}}}]}
                    ],
                },
            }
        )
        reader = DictReader(
            {"policy.yaml": policy, ".deploystack/test": "kind: [unclosed\n"}
        )
        request = SourceRequest(
            code_repository_id="r",
            release_id="v1.0.0",
            extracted_at=EXTRACTED_AT,
            manifest_paths=("policy.yaml", ".deploystack/test"),
        )

        outcome = ConfigurationScan(reader).collect(request)

        assert outcome.records, "the readable policy still produced its rule"
        assert ".deploystack/test" in (outcome.reason or "")


class TestPermissionDirection:
    """A policy is written from the receiving workload's side.

    Reading an admitted peer as the callee rather than the caller inverts
    every rule in the corpus, and the result still looks like a plausible set
    of permissions. Nothing else in this subcomponent fails that quietly.
    """

    def test_an_admitted_peer_is_the_caller(self):
        records = scan("v0.10.0").records
        permitted = {
            (r.subject, r.object)
            for r in records
            if r.constraint is ConstraintKind.MAY_CALL
        }

        assert ("frontend", "cartservice") in permitted
        assert ("cartservice", "frontend") not in permitted

    def test_an_egress_peer_is_the_callee(self):
        """The other half of the same document, which the subject system does
        not use and a policy set elsewhere would."""

        policy = yaml.safe_dump(
            {
                "kind": "NetworkPolicy",
                "metadata": {"name": "frontend"},
                "spec": {
                    "podSelector": {"matchLabels": {"app": "frontend"}},
                    "egress": [
                        {"to": [{"podSelector": {"matchLabels": {"app": "payments"}}}]}
                    ],
                },
            }
        )
        request = SourceRequest(
            code_repository_id="r",
            release_id="v1.0.0",
            extracted_at=EXTRACTED_AT,
            manifest_paths=("policy.yaml",),
        )

        records = ConfigurationScan(DictReader({"policy.yaml": policy})).collect(
            request
        ).records

        assert [(r.subject, r.object) for r in records] == [("frontend", "payments")]

    def test_a_permission_written_twice_is_one_record(self):
        """The same rule can appear as what the callee admits and as what the
        caller may reach. It is one decision, so it is one record."""

        documents = {
            "a.yaml": yaml.safe_dump(
                {
                    "kind": "NetworkPolicy",
                    "metadata": {"name": "b"},
                    "spec": {
                        "podSelector": {"matchLabels": {"app": "b"}},
                        "ingress": [
                            {"from": [{"podSelector": {"matchLabels": {"app": "a"}}}]}
                        ],
                    },
                }
            ),
            "b.yaml": yaml.safe_dump(
                {
                    "kind": "NetworkPolicy",
                    "metadata": {"name": "a"},
                    "spec": {
                        "podSelector": {"matchLabels": {"app": "a"}},
                        "egress": [
                            {"to": [{"podSelector": {"matchLabels": {"app": "b"}}}]}
                        ],
                    },
                }
            ),
        }
        request = SourceRequest(
            code_repository_id="r",
            release_id="v1.0.0",
            extracted_at=EXTRACTED_AT,
            manifest_paths=tuple(documents),
        )

        records = ConfigurationScan(DictReader(documents)).collect(request).records

        assert len(records) == 1


class TestWhereIdentityIsDeclared:
    """The change between the two releases, and the whole temporal claim.

    The identity overlay is a shared, opt-in component at one release and gone
    at the next, with the new workload declaring its own identity beside
    itself. Both positions are committed files at tagged releases, which is
    what makes the supersession a measurement rather than a fixture.
    """

    def test_the_earlier_release_declares_identity_in_a_shared_overlay(self):
        rules = [
            r
            for r in scan("v0.9.0").records
            if r.constraint is ConstraintKind.MUST_CALL_VIA
        ]

        assert [r.decision_id for r in rules] == ["sa-shared-component"]
        assert rules[0].object == "kustomize/components/service-accounts"

    def test_the_later_release_declares_it_beside_the_workload(self):
        rules = [
            r
            for r in scan("v0.10.0").records
            if r.constraint is ConstraintKind.MUST_CALL_VIA
        ]

        assert [r.decision_id for r in rules] == ["sa-inline-with-workload"]
        assert rules[0].rationale

    def test_a_release_with_no_identity_manifests_states_no_rule(self):
        request = SourceRequest(
            code_repository_id="r",
            release_id="v1.0.0",
            extracted_at=EXTRACTED_AT,
            manifest_paths=(),
        )

        outcome = ConfigurationScan(DictReader({})).collect(request)

        assert outcome.records == ()
        assert outcome.ran is True
        assert outcome.reason


class TestDeclaredRecords:
    """The source the research assumed, and the repository that has none."""

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_repository_keeps_no_decision_records(self, release):
        """The empirical finding the rest of the design rests on."""

        outcome = RepositoryDecisionRecords(WorkspaceReader()).collect(
            request_for(release)
        )

        assert outcome.ran is True
        assert outcome.records == ()
        assert outcome.reason == "no decision records in this repository"

    def test_a_record_is_read_with_its_interval_and_its_provenance(self):
        document = (
            "---\n"
            "id: ADR-014\n"
            "subject: checkoutservice\n"
            "constraint: must_not_call\n"
            "object: paymentservice\n"
            "valid_from: v0.9.0\n"
            "supersedes: ADR-005\n"
            "rationale: Payment moves behind the billing gateway.\n"
            "---\n\n"
            "# Payment access\n"
        )
        reader = DictReader({"docs/adr/0014-payment.md": document})

        records = RepositoryDecisionRecords(reader).collect(request_for("v0.10.0")).records

        assert len(records) == 1
        record = records[0]
        assert record.decision_id == "ADR-014"
        assert record.constraint is ConstraintKind.MUST_NOT_CALL
        assert record.valid_from == "v0.9.0"
        assert record.supersedes == "ADR-005"
        assert record.source_tier is SourceTier.DECISION_RECORD
        assert record.source_strength is EvidenceStrength.AUTHORITATIVE
        assert record.extraction_method is ExtractionMethod.DECLARED

    def test_ordinary_markdown_is_not_a_decision_record(self):
        reader = DictReader({"README.md": "# The system\n\nIt does things.\n"})

        assert RepositoryDecisionRecords(reader).collect(request_for("v0.10.0")).records == ()

    def test_a_record_missing_its_interval_raises_rather_than_being_guessed(self):
        reader = DictReader(
            {
                "docs/adr/0001-x.md": (
                    "---\nid: ADR-001\nsubject: a\nconstraint: may_call\nobject: b\n---\n"
                )
            }
        )

        with pytest.raises(DecisionSourceError, match="valid_from"):
            RepositoryDecisionRecords(reader).collect(request_for("v0.10.0"))

    def test_a_constraint_outside_the_vocabulary_raises(self):
        reader = DictReader(
            {
                "adr/0002-y.md": (
                    "---\nid: ADR-002\nsubject: a\nconstraint: should_probably_avoid\n"
                    "object: b\nvalid_from: v1.0.0\n---\n"
                )
            }
        )

        with pytest.raises(DecisionSourceError, match="should_probably_avoid"):
            RepositoryDecisionRecords(reader).collect(request_for("v0.10.0"))

    def test_an_unnamed_decision_repository_reports_that_it_did_not_run(self):
        """Different from finding nothing. One says the architects keep no
        decisions; the other says nobody told us where they are."""

        outcome = ExternalDecisionRecords(WorkspaceReader()).collect(
            request_for("v0.10.0")
        )

        assert outcome.ran is False
        assert outcome.records == ()
        assert outcome.reason == "no decision repository was named"


class TestWhatEachModeWouldFind:
    """The numbers the mode picker shows before anything is chosen."""

    @pytest.mark.parametrize("release", RELEASES)
    def test_tier_one_runs_and_finds_nothing(self, release):
        """An adapter that was skipped establishes nothing. This one ran."""

        available = DecisionKnowledgeService(WorkspaceReader()).availability(
            request_for(release)
        )

        assert available["repo_adr"].ran is True
        assert available["repo_adr"].records == 0
        assert available["repo_adr"].reason == "no decision records in this repository"

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_combined_mode_is_the_only_one_with_anything_in_it(self, release):
        available = DecisionKnowledgeService(WorkspaceReader()).availability(
            request_for(release)
        )

        assert available["combined"].records == 25
        assert available["combined"].by_source == {"config_scan": 25}
        assert available["combined"].reason is None

    def test_a_mode_that_cannot_run_says_so_rather_than_reporting_zero(self):
        available = DecisionKnowledgeService(WorkspaceReader()).availability(
            request_for("v0.10.0")
        )

        assert available["external_adr"].ran is False
        assert available["external_adr"].reason == "no decision repository was named"

    def test_every_mode_is_reported_whether_or_not_it_was_asked_for(self):
        """The refusal message names the mode that would work, so the yields
        have to be computed for all three rather than for the chosen one."""

        available = DecisionKnowledgeService(WorkspaceReader()).availability(
            request_for("v0.10.0")
        )

        assert set(available) == set(registered_modes())

    def test_an_unknown_mode_is_refused_by_name(self):
        with pytest.raises(ValueError, match="repo_adr"):
            sources_for("whatever_we_can_find", WorkspaceReader())

    def test_combined_reads_the_declared_source_before_the_reconstructed_one(self):
        """Where a written decision and a reconstructed rule speak about one
        relationship, the written one should be the first the log holds."""

        order = [source.name for source in sources_for("combined", WorkspaceReader())]

        assert order == ["external_adr", "config_scan"]

class TestWhereARuleWasRead:
    """A citation has to be showable, which means lines rather than a file.

    Only whatever parsed the document knows which line a rule came from, so
    the scan records it. Evidence retrieval quotes exactly those lines; it
    does not go looking for them again, because a second reader of one file is
    two chances to disagree about what a rule is.
    """

    @pytest.mark.parametrize("release", RELEASES)
    def test_a_permission_points_at_the_entry_that_created_it(self, release):
        """A policy names its own workload in the selector and the peers it
        admits after it. The rule comes from the peer entry, not the selector."""

        record = next(
            r for r in scan(release).records
            if r.decision_id == "rule-frontend-cartservice"
        )
        quoted = (SUBJECT / release / record.source_span.path).read_text(
            encoding="utf-8"
        ).splitlines()[record.source_span.start_line - 1]

        assert "app: frontend" in quoted

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_default_refusal_points_at_its_whole_document(self, release):
        """It is a rule about every pair, so no single line states it."""

        record = next(
            r for r in scan(release).records if r.decision_id == "np-deny-all"
        )

        assert record.source_span.start_line == 1
        assert record.source_span.end_line > 1

    @pytest.mark.parametrize("release", RELEASES)
    def test_a_declared_operation_points_at_the_line_that_declares_it(self, release):
        record = next(
            r for r in scan(release).records
            if r.decision_id == "rpc-cartservice-additem"
        )
        quoted = (SUBJECT / release / record.source_span.path).read_text(
            encoding="utf-8"
        ).splitlines()[record.source_span.start_line - 1]

        assert "rpc AddItem" in quoted

    def test_an_inline_identity_points_at_the_document_inside_the_file(self):
        """The manifest holds a Deployment, a Service and a ServiceAccount.
        The rule is about the third, so the span is the third document's
        range rather than the file's."""

        record = next(
            r for r in scan("v0.10.0").records
            if r.decision_id == "sa-inline-with-workload"
        )
        lines = (SUBJECT / "v0.10.0" / record.source_span.path).read_text(
            encoding="utf-8"
        ).splitlines()
        quoted = lines[record.source_span.start_line - 1 : record.source_span.end_line]

        assert any("kind: ServiceAccount" in line for line in quoted)
        assert not any("kind: Deployment" in line for line in quoted)

    def test_a_rule_about_a_directory_has_no_span(self):
        """A directory has no lines. `None` is the honest answer, and it is
        legal - a decision ratified by a person has no document either."""

        record = next(
            r for r in scan("v0.9.0").records
            if r.decision_id == "sa-shared-component"
        )

        assert record.source_span is None

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_span_lands_inside_the_file_it_names(self, release):
        for record in scan(release).records:
            if record.source_span is None:
                continue
            lines = (SUBJECT / release / record.source_span.path).read_text(
                encoding="utf-8"
            ).splitlines()

            assert 1 <= record.source_span.start_line <= len(lines)
            assert record.source_span.start_line <= record.source_span.end_line <= len(lines)

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_span_survives_the_log(self, release):
        """It has to reach evidence retrieval, which reads the log rather than
        the scan."""

        record = next(
            r for r in scan(release).records
            if r.decision_id == "rule-frontend-cartservice"
        )
        event = record.to_event()

        assert event["source_span"]["start_line"] == record.source_span.start_line
