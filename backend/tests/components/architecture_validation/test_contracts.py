"""Boundary contract tests for architecture validation.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Checks the two shapes that cross a component boundary, against committed
    fixtures. A contract is only frozen once a fixture exists for it: a shape
    that merely compiles is still an opinion, and it moves the moment real data
    arrives.

    The node-link test is written as the exact call the consuming component
    will make. NetworkX 3.6 changed its default edge key from "links" to
    "edges", so the keyword is passed explicitly on both sides. On the
    installed 3.7 a mismatch raises `KeyError` rather than producing an
    edgeless graph - measured in `test_graph_publishing.py`, and the opposite
    of what this docstring used to claim.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.components.architecture_validation.models import (
    ConstraintKind,
    DecisionRecord,
    EvidenceItem,
    EvidencePackage,
    EvidenceRole,
    EvidenceStrength,
    ExtractionMethod,
    RelationshipKind,
    SourceTier,
    Span,
)
from app.domain.recovered_architecture import (
    ArchitectureStyle,
    DerivationMethod,
    EvidenceQuality,
    RecoveredArchitecture,
    StyleSource,
)
from app.domain.validated_architecture import (
    NODE_LINK_EDGE_KEY,
    ReleaseDateSource,
    RunMode,
    SizeUnitConflict,
    ValidatedArchitectureGraph,
    ValidatedEdge,
    ValidatedNode,
    ValidationBucket,
    ValidationRollup,
    ValidationRunStamp,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "validation"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def build_graph() -> ValidatedArchitectureGraph:
    """A minimal published graph, built the way the publisher builds one.

    Every field of schema 1.3.0 is set to something a consumer would have to
    handle, because the fixture is what they develop against: four of the six
    fields this version added were asked for after loading the 1.0.0 fixture,
    and a field left at its default in here is a field nobody finds until
    integration week.
    """

    rollup = ValidationRollup(confirmed=1)
    return ValidatedArchitectureGraph(
        repository_id="online-boutique",
        release_id="v0.9.0",
        architecture_style=ArchitectureStyle.MICROSERVICES,
        architecture_style_source=StyleSource.INFERRED_BY_C2,
        nodes=(
            ValidatedNode(
                "svc:checkoutservice",
                "checkoutservice",
                "service",
                rollup,
                canonical="checkout",
                size=1420.0,
                size_unit="loc",
            ),
            ValidatedNode(
                "svc:paymentservice",
                "paymentservice",
                "service",
                rollup,
                canonical="payment",
                size=860.0,
                size_unit="loc",
            ),
        ),
        edges=(
            ValidatedEdge(
                fact_id="f3a1",
                source_id="svc:checkoutservice",
                target_id="svc:paymentservice",
                relationship="communicates-with",
                bucket=ValidationBucket.CONFIRMED,
                confidence=0.78,
                governing_decision="np-checkoutservice",
                evidence_refs=("ev:np-checkoutservice:1",),
                source_tier=SourceTier.EXECUTABLE_CONFIG,
                model_calls=2,
                produced_by="model",
                verification_outcome="agree",
                arbiter_agreement="agreed",
                route="publish",
                evidence_hash="b" * 16,
                confidence_terms={
                    "verdict_base": 0.50,
                    "source_strength_authoritative": 0.25,
                },
                confidence_ceiling="unverified_by_choice",
                confidence_maximum=0.85,
                attributes={"interaction": "grpc"},
            ),
        ),
        stamp=ValidationRunStamp(
            run_id="run-0001",
            generated_at=datetime(2026, 10, 14),
            mode=RunMode.RECONSTRUCTION,
            reasoner_model="openai/gpt-oss-20b",
            verifier_model="qwen/qwen3-32b",
            prompt_versions=("critical_reframing@1", "primary_verdict@1"),
        ),
        validation_confidence=0.78,
        released_at=datetime(2025, 4, 1, tzinfo=UTC),
        released_at_source=ReleaseDateSource.TAGGER,
        release_order_key=(0, 0, 9, 0, 0, 4, 0, 1, 0),
        c1_model_ref="98e60f5ee0b643cc00bceb71e6efb89617740432",
        summary={"facts": 1, "published": 1, "review": 0},
    )


class TestRecoveredArchitectureContract:
    """The shape architecture recovery hands over."""

    def test_the_committed_fixture_has_every_field_the_contract_declares(self):
        document = load("recovered_v0.9.0.json")

        assert document["schema_version"] == "1.0.0"
        assert set(document) == {
            "schema_version",
            "repository_id",
            "release_id",
            "style",
            "elements",
            "relationships",
            "manifest_paths",
            "provenance",
        }
        assert document["style"] in set(ArchitectureStyle)
        for element in document["elements"]:
            assert element["quality"] in set(EvidenceQuality)
        for relationship in document["relationships"]:
            assert relationship["derived_by"] in set(DerivationMethod)

    def test_a_release_with_no_relationships_is_valid_and_says_so(self):
        """Recovery reports links to components, not between them, so this is
        the shape that actually arrives today."""

        architecture = RecoveredArchitecture(
            repository_id="online-boutique",
            release_id="v0.9.0",
            style=ArchitectureStyle.MICROSERVICES,
            style_source=StyleSource.C1,
            elements=(),
            relationships=(),
            provenance=_provenance(),
        )

        assert architecture.has_element_relationships is False

    def test_an_undeterminable_style_is_representable(self):
        """Guessing a style would be worse than admitting to none."""

        assert ArchitectureStyle.UNKNOWN in set(ArchitectureStyle)


class TestValidatedArchitectureContract:
    """The shape degradation detection receives."""

    def test_the_edge_list_is_published_under_the_links_key(self):
        """The one defect in this handover that fails silently."""

        document = build_graph().to_node_link()

        assert NODE_LINK_EDGE_KEY == "links"
        assert "links" in document
        assert "edges" not in document
        assert len(document["links"]) == 1

    def test_every_verdict_travels_on_the_relationship_it_describes(self):
        """So the consumer never has to join findings back onto a topology."""

        edge = build_graph().to_node_link()["links"][0]

        assert edge["source"] == "svc:checkoutservice"
        assert edge["target"] == "svc:paymentservice"
        assert edge["bucket"] == ValidationBucket.CONFIRMED
        assert edge["governing_decision"] == "np-checkoutservice"
        assert edge["evidence_refs"] == ["ev:np-checkoutservice:1"]

    def test_the_built_document_matches_the_committed_fixture_exactly(self):
        """The fixture is what the consumer develops against, so it has to be
        the same bytes this code produces."""

        assert build_graph().to_node_link() == load("validated_v0.9.0.graph.json")

    def test_the_graph_block_declares_every_field_of_this_schema(self):
        """Pinned as a set, so a field that disappears is a failure here
        rather than a `None` in somebody else's component.

        Four of these were asked for by the consumer after they loaded the
        1.0.0 fixture into their own ingestion; two more were found by reading
        their boundary model against the same file.
        """

        graph = build_graph().to_node_link()["graph"]

        assert graph["schema_version"] == "1.3.0"
        assert set(graph) == {
            "schema_version",
            "generator",
            "repository_id",
            "release_id",
            "released_at",
            "released_at_source",
            "release_order_key",
            "c1_model_ref",
            "architecture_style",
            "architecture_style_source",
            "validation_confidence",
            "run",
            "summary",
        }

    def test_the_release_date_says_which_git_field_produced_it(self):
        """So a suspicious ordering downstream is traceable to the field that
        ordered it. The committer date is never one of them: it is rewritten
        by every rebase and reads as today."""

        graph = build_graph().to_node_link()["graph"]

        assert graph["released_at_source"] in set(ReleaseDateSource)
        assert "committer" not in set(ReleaseDateSource)

    def test_the_ordering_key_does_not_depend_on_a_date_at_all(self):
        """Published beside the date because the two fail differently. When a
        date order and a version order disagree, that is a back-ported release
        rather than a bug - and one field alone cannot see it."""

        graph = build_graph().to_node_link()["graph"]

        assert graph["release_order_key"] == [0, 0, 9, 0, 0, 4, 0, 1, 0]

    def test_the_confidence_the_consumer_gates_on_cannot_be_left_unset(self):
        """It has no default at the consumer's request: a document built
        without it would publish 0.0 and silently drop the release from their
        whole analysis, with no error anywhere."""

        with pytest.raises(TypeError):
            ValidatedArchitectureGraph(
                repository_id="online-boutique",
                release_id="v0.9.0",
                architecture_style=ArchitectureStyle.MICROSERVICES,
                nodes=(),
                edges=(),
                stamp=build_graph().stamp,
            )

    def test_a_confidence_outside_the_agreed_bounds_cannot_be_built(self):
        with pytest.raises(ValueError, match="0..1"):
            replace(build_graph(), validation_confidence=1.4)

    def test_a_release_measuring_size_two_ways_cannot_be_built(self):
        """A trend across mixed units compares nothing, with no error
        anywhere, because both are numbers."""

        rollup = ValidationRollup(confirmed=1)
        with pytest.raises(SizeUnitConflict):
            replace(
                build_graph(),
                nodes=(
                    ValidatedNode("a", "a", "service", rollup, size=1, size_unit="loc"),
                    ValidatedNode("b", "b", "service", rollup, size=2, size_unit="bytes"),
                ),
            )

    def test_the_node_carries_an_identity_that_survives_a_renamed_directory(self):
        """Recovery's element id is stable across the releases on record, but
        the derivation belongs to another component and is not a hash of the
        name or the path - so history is followed by this component's own
        canonical name instead."""

        node = build_graph().to_node_link()["nodes"][0]

        assert node["id"] == "svc:checkoutservice"
        assert node["canonical"] == "checkout"

    def test_the_run_stamp_records_what_produced_every_verdict(self):
        run = build_graph().to_node_link()["graph"]["run"]

        assert set(run) >= {"run_id", "mode", "reasoner_model", "verifier_model", "prompt_versions"}
        assert run["mode"] in set(RunMode)

    def test_model_calls_are_published_per_edge(self):
        """An uncovered relationship reaches its bucket with zero calls, and
        the number has to be visible for that to be demonstrable."""

        assert build_graph().to_node_link()["links"][0]["model_calls"] == 2


class TestDecisionRecordProvenance:
    """Provenance is structural, not a convention."""

    def test_a_decision_record_cannot_be_built_without_provenance(self):
        with pytest.raises(TypeError):
            DecisionRecord(
                decision_id="d1",
                subject="checkoutservice",
                constraint=ConstraintKind.MUST_NOT_CALL,
                object="redis-cart",
                valid_from="v0.9.0",
                valid_to=None,
            )

    def test_a_complete_record_serialises_its_provenance(self):
        record = _decision()

        event = record.to_event()

        assert event["source_tier"] == SourceTier.EXECUTABLE_CONFIG
        assert event["source_strength"] == EvidenceStrength.AUTHORITATIVE
        assert event["extraction_method"] == ExtractionMethod.RECONSTRUCTED
        assert event["source_ref"].endswith(".yaml")

    def test_a_reconstructed_record_keeps_its_extraction_method_once_ratified(self):
        """Clearing it would let the pipeline manufacture its own ground
        truth."""

        ratified = _decision(ratified_by="architect")

        assert ratified.extraction_method is ExtractionMethod.RECONSTRUCTED
        assert ratified.ratified_by == "architect"


class TestEvidencePackage:
    """What the model is allowed to reason from."""

    def test_the_package_exposes_its_references_for_citation_checking(self):
        """A schema can require a citation to exist; only this set can
        establish that it refers to something real."""

        package = EvidencePackage(
            fact_id="f3a1",
            subject="checkoutservice",
            relationship=RelationshipKind.COMMUNICATES_WITH,
            object="paymentservice",
            release_id="v0.10.0",
            evidence_hash="abc123",
            items=(
                EvidenceItem(
                    ref="ev:np-checkoutservice:1",
                    role=EvidenceRole.RULE,
                    text="egress to paymentservice on 50051",
                    span=Span("kustomize/components/network-policies/np.yaml", 12, 18),
                ),
            ),
        )

        assert package.refs == frozenset({"ev:np-checkoutservice:1"})
        assert "ADR-999" not in package.refs

    def test_truncation_is_recorded_rather_than_silent(self):
        package = EvidencePackage(
            fact_id="f3a1",
            subject="checkoutservice",
            relationship=RelationshipKind.COMMUNICATES_WITH,
            object="paymentservice",
            release_id="v0.10.0",
            evidence_hash="abc123",
            items=(),
            truncated=True,
            dropped_roles=(EvidenceRole.STRUCTURAL_CONTEXT,),
        )

        assert package.truncated is True
        assert EvidenceRole.STRUCTURAL_CONTEXT in package.dropped_roles


def _provenance():
    from app.domain.recovered_architecture import RecoveryProvenance

    return RecoveryProvenance(
        reader="fixture_reader",
        source_schema_version="1.0.0",
        source_reference="tests/fixtures/validation/recovered_v0.9.0.json",
    )


def _decision(**overrides) -> DecisionRecord:
    values = {
        "decision_id": "np-checkoutservice",
        "subject": "checkoutservice",
        "constraint": ConstraintKind.MAY_CALL,
        "object": "paymentservice",
        "valid_from": "v0.9.0",
        "valid_to": None,
        "source": "config_scan",
        "source_repository": "online-boutique",
        "source_tier": SourceTier.EXECUTABLE_CONFIG,
        "source_strength": EvidenceStrength.AUTHORITATIVE,
        "source_ref": "kustomize/components/network-policies/network-policy-checkoutservice.yaml",
        "extraction_method": ExtractionMethod.RECONSTRUCTED,
        "extracted_at": datetime(2026, 10, 14),
    }
    values.update(overrides)
    return DecisionRecord(**values)
