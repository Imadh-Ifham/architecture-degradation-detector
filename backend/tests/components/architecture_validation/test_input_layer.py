"""Input layer tests: translation, style adapters and fact identity.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Covers the boundary that absorbs recovery's output and the subject system's
    architectural style.

    The dependency stand-in's tests moved to `tests/infrastructure/` along with
    the code. What they exercise is infrastructure standing in for an upstream
    component, and this component can no longer reach a file at all - which
    `test_architecture_rules.py` now asserts.

    Three tests here carry more weight than the rest. `TestReleaseOrdering`
    covers the one place where the component can be confidently wrong with no
    exception anywhere: compared as text, the newer of the two releases the
    demonstration uses sorts first. The event-driven collapse
    is what makes "style-agnostic" a property rather than a claim: a design
    that cannot turn a publish/subscribe pair through a channel into one
    relationship would need an event-driven special case in every rule
    downstream. And the schema-bump test is what turns a recovery change from a
    mystery into a message.
"""

import pytest

from app.components.architecture_validation.observation_normalization import (
    ObservationNormalizationService,
)
from app.components.architecture_validation.observation_normalization._identity import (
    canonical_name,
    collisions,
    fact_id,
)
from app.components.architecture_validation.observation_normalization._release import (
    RELEASE_SEGMENTS,
    UnorderableRelease,
    release_sort_key,
)
from app.components.architecture_validation.observation_normalization.styles import (
    adapter_for,
    registered_styles,
)
from app.components.architecture_validation.models import RelationshipKind
from app.domain.recovered_architecture import (
    ArchitectureElement,
    ArchitectureRelationship,
    ArchitectureStyle,
    DerivationMethod,
    ElementKind,
    EvidenceQuality,
    IncoherentArchitecture,
    RecoveredArchitecture,
    RecoveryProvenance,
    StyleSource,
)
from app.components.architecture_validation.observation_normalization.styles import (
    KNOWN_LABELS,
)
from app.infrastructure.recovery_gateway.inventory_schema import (
    InventoryFieldError,
    InventoryVersionError,
)
from app.infrastructure.recovery_gateway.snapshot_schema import (
    SNAPSHOT_SCHEMA_VERSION,
    SnapshotFieldError,
    SnapshotVersionError,
    parse_snapshot,
)
from app.components.architecture_validation.observation_normalization._style import (
    infer_style,
)
from app.infrastructure.recovery_gateway.translation import (
    STYLE_FIELD,
    manifest_paths,
    read_style,
    translate,
)

RELEASE = "v0.10.0"


def element(identifier, name, kind=ElementKind.SERVICE, quality=EvidenceQuality.CONFIRMED):
    return ArchitectureElement(id=identifier, name=name, kind=kind, quality=quality)


def relationship(source, target, label, quality=EvidenceQuality.CONFIRMED, **attributes):
    return ArchitectureRelationship(
        source_id=source,
        target_id=target,
        label=label,
        quality=quality,
        derived_by=DerivationMethod.RECOVERED,
        attributes=attributes,
    )


def architecture(
    style,
    elements,
    relationships,
    release=RELEASE,
    style_source=StyleSource.C1,
):
    """One architecture for a test.

    `style_source` defaults to `c1` so that a test naming a style gets that
    style. A test that wants the inference asks for it by passing
    `inferred_by_c2`, which is how a real reader asks for it too.
    """

    return RecoveredArchitecture(
        repository_id="online-boutique",
        release_id=release,
        style=style,
        style_source=style_source,
        elements=tuple(elements),
        relationships=tuple(relationships),
        provenance=RecoveryProvenance("fixture_reader", "1.0.0", "test"),
    )


def inventory(**overrides):
    document = {
        "schema_version": "1.0.0",
        "repository": {"id": "online-boutique", "commit": "abc123"},
        "components": [
            {
                "id": "svc:frontend",
                "name": "frontend",
                "kind": "deployment_service",
                "confidence": "confirmed",
                "root_path": "src/frontend",
            },
            {
                "id": "svc:paymentservice",
                "name": "paymentservice",
                "kind": "deployment_service",
                "confidence": "confirmed",
                "root_path": "src/paymentservice",
            },
            {
                "id": "dir:scripts",
                "name": "scripts",
                "kind": "directory_group",
                "confidence": "inferred",
                "root_path": "scripts",
            },
        ],
        "relationships": [
            {
                "id": "r1",
                "type": "manifest_defines_component",
                "source_kind": "file",
                "source_id": "f1",
                "target_kind": "component",
                "target_id": "svc:frontend",
                "confidence": "confirmed",
            }
        ],
        "files": [
            {
                "id": "f1",
                "path": "kustomize/base/frontend.yaml",
                "category": "deployment_manifest",
                "component_id": "svc:frontend",
            },
            {
                "id": "f2",
                "path": "src/frontend/main.go",
                "category": "source_code",
                "component_id": "svc:frontend",
            },
        ],
    }
    document.update(overrides)
    return document


def do_translate(document=None, **kwargs):
    arguments = {
        "repository_id": "online-boutique",
        "release_id": RELEASE,
        "source_reference": "test",
        "reader": "fixture_reader",
    }
    arguments.update(kwargs)
    return translate(document if document is not None else inventory(), **arguments)


class TestInventoryTranslation:
    """Recovery's output, read through one file."""

    def test_only_architectural_component_kinds_become_elements(self):
        """A directory group is a filesystem fact, not an architectural one."""

        result = do_translate()

        assert {e.id for e in result.elements} == {"svc:frontend", "svc:paymentservice"}
        assert "dir:scripts" not in {e.id for e in result.elements}

    def test_an_inferred_component_keeps_its_quality(self):
        document = inventory()
        document["components"][0]["confidence"] = "inferred"

        result = do_translate(document)

        found = next(e for e in result.elements if e.id == "svc:frontend")
        assert found.quality is EvidenceQuality.INFERRED

    def test_relationships_arrive_empty_because_recovery_reports_none(self):
        """Every inventory relationship type points *at* a component."""

        result = do_translate()

        assert result.relationships == ()
        assert result.has_element_relationships is False

    def test_only_manifest_files_are_attached_as_source_paths(self):
        result = do_translate()

        frontend = next(e for e in result.elements if e.id == "svc:frontend")
        assert frontend.source_paths == ("kustomize/base/frontend.yaml",)

    def test_elements_are_sorted_so_two_translations_are_identical(self):
        """Fact ids would survive reordering; a fixture diff would not."""

        first = do_translate()
        second = do_translate()

        assert [e.id for e in first.elements] == [e.id for e in second.elements]
        assert [e.id for e in first.elements] == sorted(e.id for e in first.elements)

    def test_provenance_records_the_input_schema_version(self):
        result = do_translate()

        assert result.provenance.source_schema_version == "1.0.0"
        assert result.provenance.reader == "fixture_reader"

    def test_an_unused_new_field_is_ignored(self):
        """Recovery gaining a field is what actually happens."""

        document = inventory(runtime_traces=[{"anything": True}])
        document["components"][0]["new_upstream_field"] = "whatever"

        assert do_translate(document).elements

    def test_a_schema_bump_fails_loudly_and_names_both_versions(self):
        with pytest.raises(InventoryVersionError) as caught:
            do_translate(inventory(schema_version="2.0.0"))

        message = str(caught.value)
        assert "schema 2.0.0" in message
        assert "targets 1.0.0" in message

    def test_a_missing_required_field_names_the_field(self):
        document = inventory()
        del document["components"]

        with pytest.raises(InventoryFieldError) as caught:
            do_translate(document)

        assert caught.value.field == "components"

    def test_manifest_paths_are_exposed_for_the_derivation(self):
        assert manifest_paths(inventory()) == ("kustomize/base/frontend.yaml",)


class TestStyleProvenance:
    """Whose answer the architectural style is.

    The style selects the adapter and the adapter decides what every fact in
    the run looks like, so an unlabelled style quietly changes every verdict
    downstream. These keep the authority question answered in code rather than
    in prose.
    """

    def test_recovery_supplies_no_style_today_and_the_gateway_says_so(self):
        style, source = read_style(inventory())

        assert style is ArchitectureStyle.UNKNOWN
        assert source is StyleSource.INFERRED_BY_C2

    def test_a_style_recovery_wrote_is_recoverys_answer(self):
        style, source = read_style(inventory(**{STYLE_FIELD: "layered"}))

        assert style is ArchitectureStyle.LAYERED
        assert source is StyleSource.C1

    def test_unknown_from_recovery_is_an_answer_not_a_gap(self):
        """Recovery looked and could not tell. That is a different thing from
        recovery not having looked, and only `style_source` separates them."""

        style, source = read_style(inventory(**{STYLE_FIELD: "unknown"}))

        assert style is ArchitectureStyle.UNKNOWN
        assert source is StyleSource.C1

    def test_a_style_this_version_does_not_know_is_still_recoverys_answer(self):
        """Ordinary drift between two components built in parallel. The run
        normalises generically and caps its confidence; it does not stop."""

        style, source = read_style(inventory(**{STYLE_FIELD: "hexagonal"}))

        assert style is ArchitectureStyle.UNKNOWN
        assert source is StyleSource.C1

    def test_recoverys_style_is_not_second_guessed(self):
        """The shape says microservices. Recovery said layered. Recovery wins."""

        outcome = ObservationNormalizationService().normalise(
            architecture(
                ArchitectureStyle.LAYERED,
                [element("a", "frontend"), element("b", "paymentservice")],
                [relationship("a", "b", "grpc")],
                style_source=StyleSource.C1,
            )
        )

        assert outcome.style_resolved == ArchitectureStyle.LAYERED
        assert outcome.style_source == StyleSource.C1
        assert all(fact.style_source == "c1" for fact in outcome.facts)

    def test_an_absent_style_is_inferred_and_says_so(self):
        outcome = ObservationNormalizationService().normalise(
            architecture(
                ArchitectureStyle.UNKNOWN,
                [element("a", "frontend"), element("b", "paymentservice")],
                [relationship("a", "b", "grpc")],
                style_source=StyleSource.INFERRED_BY_C2,
            )
        )

        assert outcome.style_resolved == ArchitectureStyle.MICROSERVICES
        assert outcome.style_source == StyleSource.INFERRED_BY_C2
        assert all(fact.style_source == "inferred_by_c2" for fact in outcome.facts)
        assert any("inferred" in warning for warning in outcome.warnings)

    def test_an_undeterminable_style_normalises_generically_rather_than_guessing(self):
        outcome = ObservationNormalizationService().normalise(
            architecture(
                ArchitectureStyle.UNKNOWN,
                [],
                [],
                style_source=StyleSource.INFERRED_BY_C2,
            )
        )

        assert outcome.style_resolved == "generic"
        assert outcome.warnings

    def test_every_fact_says_where_its_style_came_from(self):
        """No third value and no empty one. A fact read on its own has to
        carry the answer, because the strength of a verdict about it depends
        on whose answer it was."""

        for source in (StyleSource.C1, StyleSource.INFERRED_BY_C2):
            outcome = ObservationNormalizationService().normalise(
                architecture(
                    ArchitectureStyle.MICROSERVICES,
                    [element("a", "frontend"), element("b", "paymentservice")],
                    [relationship("a", "b", "grpc")],
                    style_source=source,
                )
            )

            assert outcome.facts
            assert {fact.style_source for fact in outcome.facts} == {source}


class TestStyleInference:
    """What the architecture alone can and cannot establish.

    Narrow on purpose. Each rule is something the input states outright; none
    of them is a heuristic dressed up as a classification.
    """

    def test_two_deployed_services_is_microservices(self):
        assert (
            infer_style((element("a", "frontend"), element("b", "paymentservice")))
            is ArchitectureStyle.MICROSERVICES
        )

    def test_layer_named_components_are_layered(self):
        elements = (
            element("m:p", "PresentationLayer", kind=ElementKind.MODULE),
            element("m:d", "DomainLayer", kind=ElementKind.MODULE),
        )

        assert infer_style(elements) is ArchitectureStyle.LAYERED

    def test_one_layer_name_is_not_a_layered_architecture(self):
        """A component called `domain` is a component called domain."""

        elements = (
            element("m:d", "DomainLayer", kind=ElementKind.MODULE),
            element("m:x", "helpers", kind=ElementKind.MODULE),
        )

        assert infer_style(elements) is ArchitectureStyle.UNKNOWN

    def test_a_single_element_is_a_monolith(self):
        assert (
            infer_style((element("m:app", "app", kind=ElementKind.MODULE),))
            is ArchitectureStyle.MONOLITH
        )

    def test_one_deployed_service_is_not_microservices(self):
        """One deployed service is a deployed monolith."""

        assert (
            infer_style((element("a", "frontend"),))
            is not ArchitectureStyle.MICROSERVICES
        )

    def test_event_driven_is_never_inferred(self):
        """Recognising it needs evidence of a broker and of publish and
        subscribe pairs. Nothing upstream supplies either, so claiming the
        style would be a guess."""

        elements = (
            element("s:a", "a", kind=ElementKind.MODULE),
            element("s:b", "b", kind=ElementKind.MODULE),
        )

        assert infer_style(elements) is not ArchitectureStyle.EVENT_DRIVEN

    def test_nothing_at_all_is_undetermined_rather_than_a_monolith(self):
        assert infer_style(()) is ArchitectureStyle.UNKNOWN


class TestStyleAdapters:
    """One canonical shape, whatever the style."""

    def test_four_styles_have_a_dedicated_adapter(self):
        assert set(registered_styles()) == {
            ArchitectureStyle.MICROSERVICES,
            ArchitectureStyle.LAYERED,
            ArchitectureStyle.EVENT_DRIVEN,
            ArchitectureStyle.MONOLITH,
        }

    @pytest.mark.parametrize(
        "style",
        [
            ArchitectureStyle.MICROSERVICES,
            ArchitectureStyle.LAYERED,
            ArchitectureStyle.MONOLITH,
            ArchitectureStyle.UNKNOWN,
            "banana",
        ],
    )
    def test_every_style_produces_the_same_canonical_shape(self, style):
        """One validation algorithm, every style."""

        given = architecture(
            style,
            [element("a", "alpha"), element("b", "beta")],
            [relationship("a", "b", "http")],
        )

        facts = adapter_for(style).normalise(given)

        assert len(facts) == 1
        assert facts[0].subject.name == "alpha"
        assert facts[0].object.name == "beta"
        assert facts[0].relationship in set(RelationshipKind)
        assert facts[0].attributes["observed_as"] == "http"

    def test_an_unknown_style_degrades_rather_than_crashing(self):
        given = architecture(
            "banana",
            [element("a", "alpha"), element("b", "beta")],
            [relationship("a", "b", "mystery-protocol")],
        )

        outcome = ObservationNormalizationService().normalise(given)

        assert outcome.style_resolved == "generic"
        assert len(outcome.facts) == 1
        assert outcome.facts[0].attributes["style_not_resolved"] is True
        assert any("not resolved" in warning for warning in outcome.warnings)

    def test_a_relationship_naming_an_unknown_element_cannot_be_built_at_all(self):
        """Revised from "dropped with a warning" by OBS-D5.

        An unrecognised relationship *label* is a word we do not know and is
        absorbed. An edge pointing at a missing node is a document that does
        not hold together, and absorbing it would put a relationship in the
        validated graph with nothing on one end. The architecture refuses to
        exist, so there is no code path on which it reaches an adapter.
        """

        with pytest.raises(IncoherentArchitecture, match="ghost"):
            architecture(
                ArchitectureStyle.MICROSERVICES,
                [element("a", "alpha")],
                [relationship("a", "ghost", "http")],
            )

    def test_the_layered_adapter_records_the_rank_direction(self):
        given = architecture(
            ArchitectureStyle.LAYERED,
            [
                element("l1", "PresentationLayer", ElementKind.LAYER),
                element("l2", "DomainLayer", ElementKind.LAYER),
            ],
            [relationship("l1", "l2", "depends-on")],
        )

        fact = adapter_for(ArchitectureStyle.LAYERED).normalise(given)[0]

        assert fact.relationship is RelationshipKind.DEPENDS_ON
        assert fact.attributes["layer_rank"] == "1->4"
        assert fact.attributes["inward"] is True

    def test_an_unranked_layer_name_gets_no_invented_rank(self):
        given = architecture(
            ArchitectureStyle.LAYERED,
            [element("l1", "WidgetsLayer", ElementKind.LAYER), element("l2", "Thingies", ElementKind.LAYER)],
            [relationship("l1", "l2", "depends-on")],
        )

        fact = adapter_for(ArchitectureStyle.LAYERED).normalise(given)[0]

        assert "layer_rank" not in fact.attributes


class TestEventDrivenCollapse:
    """The case that makes style-agnostic a property rather than a claim."""

    def two_hop(self, publisher_quality=EvidenceQuality.CONFIRMED,
                subscriber_quality=EvidenceQuality.CONFIRMED):
        return architecture(
            ArchitectureStyle.EVENT_DRIVEN,
            [
                element("s:order", "OrderComponent"),
                element("ch:orders", "order-events", ElementKind.CHANNEL),
                element("s:payment", "PaymentComponent"),
            ],
            [
                relationship("s:order", "ch:orders", "publishes", publisher_quality),
                relationship("ch:orders", "s:payment", "subscribed-by", subscriber_quality),
            ],
        )

    def test_a_publish_subscribe_pair_collapses_into_one_fact(self):
        """A -> topic -> B becomes exactly one relationship, A to B."""

        facts = adapter_for(ArchitectureStyle.EVENT_DRIVEN).normalise(self.two_hop())

        assert len(facts) == 1
        assert facts[0].subject.name == "OrderComponent"
        assert facts[0].object.name == "PaymentComponent"
        assert facts[0].relationship is RelationshipKind.COMMUNICATES_WITH

    def test_the_channel_survives_as_an_attribute_not_as_an_element(self):
        facts = adapter_for(ArchitectureStyle.EVENT_DRIVEN).normalise(self.two_hop())

        assert facts[0].attributes["via"] == "order-events"
        assert facts[0].attributes["interaction"] == "async"
        assert facts[0].attributes["collapsed_hops"] == 2
        assert "order-events" not in {facts[0].subject.name, facts[0].object.name}

    def test_the_weaker_half_decides_the_quality_of_the_collapsed_fact(self):
        """A chain is only as good as its weakest hop."""

        facts = adapter_for(ArchitectureStyle.EVENT_DRIVEN).normalise(
            self.two_hop(subscriber_quality=EvidenceQuality.INFERRED)
        )

        assert facts[0].quality == EvidenceQuality.INFERRED

    def test_a_topic_with_no_subscriber_is_still_reported(self):
        """A topic nobody consumes is a real observation; dropping it would
        hide it."""

        given = architecture(
            ArchitectureStyle.EVENT_DRIVEN,
            [
                element("s:order", "OrderComponent"),
                element("ch:orders", "order-events", ElementKind.CHANNEL),
            ],
            [relationship("s:order", "ch:orders", "publishes")],
        )

        facts = adapter_for(ArchitectureStyle.EVENT_DRIVEN).normalise(given)

        assert len(facts) == 1
        assert facts[0].attributes["unpaired"] is True

    def test_a_direct_call_alongside_events_is_kept_as_itself(self):
        given = architecture(
            ArchitectureStyle.EVENT_DRIVEN,
            [
                element("s:order", "OrderComponent"),
                element("ch:orders", "order-events", ElementKind.CHANNEL),
                element("s:payment", "PaymentComponent"),
                element("s:audit", "AuditComponent"),
            ],
            [
                relationship("s:order", "ch:orders", "publishes"),
                relationship("ch:orders", "s:payment", "subscribed-by"),
                relationship("s:order", "s:audit", "grpc"),
            ],
        )

        facts = adapter_for(ArchitectureStyle.EVENT_DRIVEN).normalise(given)

        assert len(facts) == 2
        synchronous = next(f for f in facts if f.object.name == "AuditComponent")
        assert synchronous.attributes["interaction"] == "grpc"
        assert "via" not in synchronous.attributes


class TestFactIdentity:
    """Content addressing, and the name problem underneath it."""

    def test_the_same_relationship_in_one_release_gets_one_id(self):
        first = fact_id("frontend", RelationshipKind.COMMUNICATES_WITH, "paymentservice", RELEASE)
        second = fact_id("frontend", RelationshipKind.COMMUNICATES_WITH, "paymentservice", RELEASE)

        assert first == second

    def test_the_same_relationship_in_another_release_gets_another_id(self):
        """A fact is about a release, not about a repository."""

        current = fact_id("frontend", RelationshipKind.COMMUNICATES_WITH, "payment", "v0.10.0")
        previous = fact_id("frontend", RelationshipKind.COMMUNICATES_WITH, "payment", "v0.9.0")

        assert current != previous

    def test_name_spellings_of_one_service_resolve_to_one_identity(self):
        """Without this, a rule about one spelling governs none of the others."""

        assert canonical_name("payment-service") == canonical_name("paymentservice")
        assert canonical_name("PaymentService") == canonical_name("payment-service")
        assert canonical_name("payment_service") == canonical_name("paymentservice")

    def test_canonicalisation_does_not_erase_a_name(self):
        assert canonical_name("service") == "service"



def snapshot_document(**overrides):
    """A minimal valid snapshot document, for the boundary tests below."""

    document = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "repository_id": "online-boutique",
        "style": "microservices",
        "style_source": "c1",
        "elements": [
            {"id": "svc:a", "name": "frontend", "kind": "service", "quality": "confirmed"},
            {"id": "svc:b", "name": "paymentservice", "kind": "service", "quality": "confirmed"},
        ],
        "relationships": [
            {
                "source_id": "svc:a",
                "target_id": "svc:b",
                "label": "grpc",
                "quality": "confirmed",
                "derived_by": "recovered",
            }
        ],
        "manifest_paths": ["kustomize/base/frontend.yaml"],
    }
    document.update(overrides)
    return document


class TestSnapshotBoundary:
    """Three problems, three deliberately different reactions.

    The architecture document asks for a versioned schema validated before the
    receiving component accepts the package. The question that matters is not
    whether to validate but what to do on each kind of failure, and the answers
    are not the same: a word we do not know, a field we need, and a document
    that does not hold together are three different situations.
    """

    def test_a_valid_document_is_read(self):
        document = parse_snapshot(snapshot_document(), "test")

        assert document.schema_version == SNAPSHOT_SCHEMA_VERSION
        assert len(document.elements) == 2

    def test_an_unknown_field_is_ignored(self):
        """Gaining a key is what happens while a shape is still settling.
        Refusing one would make every additive change a breaking change."""

        document = parse_snapshot(
            snapshot_document(something_new={"added": "later"}), "test"
        )

        assert len(document.elements) == 2

    def test_a_missing_required_field_names_the_field_and_its_path(self):
        document = snapshot_document()
        del document["relationships"]

        with pytest.raises(SnapshotFieldError, match="relationships"):
            parse_snapshot(document, "test")

    def test_a_missing_field_inside_an_element_names_its_position(self):
        """`elements.0.name` rather than "a field is missing". A document
        written by hand is wrong in a particular place, and the path is what
        turns the message into an instruction."""

        document = snapshot_document()
        del document["elements"][0]["name"]

        with pytest.raises(SnapshotFieldError, match=r"elements\.0\.name"):
            parse_snapshot(document, "test")

    def test_every_problem_is_reported_not_only_the_first(self):
        """A hand-edited document is usually wrong in more than one place, and
        finding out one field at a time is the slow way to fix it."""

        document = snapshot_document()
        del document["elements"][0]["name"]
        del document["elements"][1]["kind"]

        with pytest.raises(SnapshotFieldError) as caught:
            parse_snapshot(document, "test")

        assert len(caught.value.problems) == 2

    def test_a_schema_version_move_names_both_versions(self):
        with pytest.raises(SnapshotVersionError) as caught:
            parse_snapshot(snapshot_document(schema_version="2.0.0"), "test")

        assert caught.value.found == "2.0.0"
        assert caught.value.targets == SNAPSHOT_SCHEMA_VERSION
        assert "2.0.0" in str(caught.value) and SNAPSHOT_SCHEMA_VERSION in str(caught.value)

    def test_the_version_is_checked_before_the_shape(self):
        """A schema move makes several fields look wrong at once. "This is
        schema 2 and I read schema 1" is a far better answer than "six fields
        are missing" when both are available."""

        document = snapshot_document(schema_version="2.0.0")
        del document["relationships"]

        with pytest.raises(SnapshotVersionError):
            parse_snapshot(document, "test")

    def test_a_missing_schema_version_is_a_field_error_not_a_version_error(self):
        document = snapshot_document()
        del document["schema_version"]

        with pytest.raises(SnapshotFieldError, match="schema_version"):
            parse_snapshot(document, "test")

    def test_the_source_is_named_so_a_reader_knows_which_file(self):
        with pytest.raises(SnapshotFieldError, match="somewhere/snapshot.json"):
            parse_snapshot({"schema_version": "1.0.0"}, "somewhere/snapshot.json")


class TestSnapshotVocabulary:
    """What happens to a word the domain vocabulary does not hold.

    Strict here, and tolerant one module over in `inventory_schema.py`. The
    reason is ownership: the inventory is recovery's document and recovery is
    still being built, so an unlearned word is not a reason to stop. The
    snapshot is ours - written and read from the same dataclasses - so an
    unrecognised kind means a hand edit or two halves of this codebase at
    different versions, and both are worth stopping for.
    """

    def read(self, tmp_path, **overrides):
        from app.infrastructure.recovery_gateway import SnapshotFileReader

        import json

        (tmp_path / "snapshot_v1.0.0.json").write_text(
            json.dumps(snapshot_document(**overrides)), encoding="utf-8"
        )
        return SnapshotFileReader(tmp_path).read("online-boutique", "v1.0.0")

    def test_an_unknown_element_kind_raises_and_lists_what_is_accepted(self, tmp_path):
        """The only two reasons to see this are a hand-edited file and a
        version skew, and both are answered by the list."""

        document = snapshot_document()
        document["elements"][0]["kind"] = "folder"

        with pytest.raises(SnapshotFieldError, match="service"):
            self.read(tmp_path, elements=document["elements"])

    def test_an_unknown_evidence_quality_raises(self, tmp_path):
        document = snapshot_document()
        document["elements"][0]["quality"] = "probably"

        with pytest.raises(SnapshotFieldError, match="probably"):
            self.read(tmp_path, elements=document["elements"])

    def test_an_unknown_style_is_undetermined_rather_than_refused(self, tmp_path):
        """The one tolerant mapping, and it has a reason of its own: a style
        has a representable "could not tell" and an element kind does not."""

        architecture = self.read(tmp_path, style="hexagonal")

        assert architecture.style is ArchitectureStyle.UNKNOWN

    def test_a_relationship_naming_an_absent_element_is_refused(self, tmp_path):
        """Not an unknown vocabulary - an incoherent document. Absorbing it
        would put an edge in the validated graph with no node on one end."""

        document = snapshot_document()
        document["relationships"][0]["target_id"] = "svc:ghost"

        with pytest.raises(IncoherentArchitecture, match="svc:ghost"):
            self.read(tmp_path, relationships=document["relationships"])

    def test_a_malformed_document_never_surfaces_as_a_type_error(self, tmp_path):
        """The regression this class exists for.

        Both error paths in this reader used to build their exception with the
        wrong number of arguments, so a malformed snapshot raised a TypeError
        from inside the error constructor - which the transport layer does not
        catch, making a bad input file a 500 rather than a 409.
        """

        import json

        for name, document in {
            "no-relationships": {"schema_version": "1.0.0", "elements": []},
            "bad-element": {
                "schema_version": "1.0.0",
                "elements": [{"id": "a"}],
                "relationships": [],
            },
        }.items():
            (tmp_path / f"snapshot_{name}.json").write_text(
                json.dumps(document), encoding="utf-8"
            )

            from app.infrastructure.recovery_gateway import SnapshotFileReader

            with pytest.raises(SnapshotFieldError):
                SnapshotFileReader(tmp_path).read("online-boutique", name)


class TestAbsorbedLabels:
    """An unrecognised relationship word is kept, not refused.

    The component diagram says this subcomponent collapses *any* architectural
    style into one fact shape, so raising on an unfamiliar word is the opposite
    of what it is for. What is not free is the consequence, which is why the
    words are counted rather than quietly folded in.
    """

    def test_an_unknown_label_is_absorbed_and_the_original_preserved(self):
        outcome = ObservationNormalizationService().normalise(
            architecture(
                ArchitectureStyle.MICROSERVICES,
                [element("a", "alpha"), element("b", "beta")],
                [relationship("a", "b", "INHERITS_FROM")],
            )
        )

        fact = outcome.facts[0]
        assert fact.relationship is RelationshipKind.DEPENDS_ON
        assert fact.attributes["observed_as"] == "INHERITS_FROM"

    def test_an_unknown_label_is_counted_and_named(self):
        outcome = ObservationNormalizationService().normalise(
            architecture(
                ArchitectureStyle.MICROSERVICES,
                [element("a", "alpha"), element("b", "beta")],
                [relationship("a", "b", "INHERITS_FROM")],
            )
        )

        assert outcome.absorbed_labels == ("INHERITS_FROM",)
        assert any("INHERITS_FROM" in warning for warning in outcome.warnings)

    def test_a_known_label_is_not_counted(self):
        outcome = ObservationNormalizationService().normalise(
            architecture(
                ArchitectureStyle.MICROSERVICES,
                [element("a", "alpha"), element("b", "beta")],
                [relationship("a", "b", "grpc")],
            )
        )

        assert outcome.absorbed_labels == ()

    def test_the_vocabulary_includes_every_adapters_words(self):
        """A check written against `base.py` alone would report `publishes` as
        unrecognised on every event-driven release, because only the
        event-driven adapter knows it."""

        assert {"publishes", "consumes", "grpc", "uses"} <= KNOWN_LABELS

    def test_a_declared_address_is_a_communication_not_a_bare_dependency(self):
        """The defect this count found.

        Recovery reports a dependency as `declared` when an artifact names both
        ends but no port identifies the protocol. Ten of the fifteen
        relationships in the subject system carry it, and the other five differ
        only in that their port was recognised - so with `declared` unmapped,
        identical evidence produced two different canonical kinds. Every
        network-policy rule the demonstration rests on is `must_not_call` or
        `may_call`, and those apply to `communicates-with` alone.
        """

        outcome = ObservationNormalizationService().normalise(
            architecture(
                ArchitectureStyle.MICROSERVICES,
                [element("a", "alpha"), element("b", "beta")],
                [relationship("a", "b", "declared")],
            )
        )

        assert outcome.facts[0].relationship is RelationshipKind.COMMUNICATES_WITH
        assert outcome.absorbed_labels == ()

    def test_the_recorded_snapshot_absorbs_nothing(self):
        """Measured on the real recording, not assumed. A non-zero count here
        would mean part of the subject architecture is a kind no rule matches."""

        from app.core.config import settings
        from app.infrastructure.recovery_gateway import SnapshotFileReader

        for release in ("v0.9.0", "v0.10.0"):
            outcome = ObservationNormalizationService().normalise(
                SnapshotFileReader(settings.snapshot_root).read("online-boutique", release)
            )

            assert outcome.absorbed_labels == (), release
            assert all(
                fact.relationship is RelationshipKind.COMMUNICATES_WITH
                for fact in outcome.facts
            ), release


class TestIdentityCollisions:
    """The guard on the one function the SO2 result rests on.

    Canonicalisation is what makes retrieval by identity possible, and the
    obvious attack on it is that it could merge two services that are
    genuinely different. These tests are the answer: it reports every case
    where it would, with both originals, so the question becomes a count
    across the corpus rather than a denial.
    """

    def test_two_names_that_collapse_are_reported_with_both_originals(self):
        outcome = ObservationNormalizationService().normalise(
            architecture(
                ArchitectureStyle.MICROSERVICES,
                [element("1", "cart"), element("2", "cart-service"), element("3", "frontend")],
                [relationship("3", "1", "grpc"), relationship("3", "2", "grpc")],
            )
        )

        collision = outcome.identity_collisions[0]
        assert set(collision.names) == {"cart", "cart-service"}
        assert collision.key == "cart"
        assert outcome.facts  # reported, not fatal

    def test_the_collision_names_both_originals_in_a_warning(self):
        """A warning a person reads, not only a structure a program reads.
        Without both spellings nobody can decide afterwards whether the merge
        was right."""

        outcome = ObservationNormalizationService().normalise(
            architecture(
                ArchitectureStyle.MICROSERVICES,
                [element("1", "cart"), element("2", "cart-service"), element("3", "frontend")],
                [relationship("3", "1", "grpc")],
            )
        )

        reported = " ".join(outcome.warnings)
        assert "cart-service" in reported and "'cart'" in reported

    def test_an_element_with_no_relationship_is_still_reported(self):
        """The question is about the architecture, not about the facts. An
        element that produced no relationship still had its identity merged."""

        outcome = ObservationNormalizationService().normalise(
            architecture(
                ArchitectureStyle.MICROSERVICES,
                [element("1", "payment-service"), element("2", "paymentservice")],
                [],
            )
        )

        assert len(outcome.identity_collisions) == 1
        assert not outcome.facts

    def test_facts_sharing_an_identity_are_merged_and_counted(self):
        """Two spellings of one element produce two relationships that hash to
        one `fact_id`, because the hash is over the canonical triple.

        Publishing both would hand on two edges carrying one identity, and
        every consumer keys on that identity - the evidence cache would be
        filled twice with different content and the reasoner paid twice for
        one question. So one survives, and the count says so.
        """

        outcome = ObservationNormalizationService().normalise(
            architecture(
                ArchitectureStyle.MICROSERVICES,
                [element("1", "cart"), element("2", "cart-service"), element("3", "frontend")],
                [relationship("3", "1", "grpc"), relationship("3", "2", "grpc")],
            )
        )

        assert len(outcome.facts) == 1
        assert outcome.merged_fact_count == 1
        assert len({fact.fact_id for fact in outcome.facts}) == len(outcome.facts)

    def test_a_merge_is_not_blamed_on_the_style_adapter(self):
        """The shortfall warning exists for a relationship naming an element
        that is not in the architecture. A merged fact did produce a fact, and
        counting it twice would attach the wrong explanation to it."""

        outcome = ObservationNormalizationService().normalise(
            architecture(
                ArchitectureStyle.MICROSERVICES,
                [element("1", "cart"), element("2", "cart-service"), element("3", "frontend")],
                [relationship("3", "1", "grpc"), relationship("3", "2", "grpc")],
            )
        )

        assert not any("produced no fact" in warning for warning in outcome.warnings)

    def test_a_healthy_snapshot_reports_nothing(self):
        """Both counters are zero on a snapshot with distinct names, so a
        non-zero pair is a finding and not noise."""

        outcome = ObservationNormalizationService().normalise(
            architecture(
                ArchitectureStyle.MICROSERVICES,
                [element("a", "frontend"), element("b", "paymentservice")],
                [relationship("a", "b", "grpc")],
            )
        )

        assert outcome.identity_collisions == ()
        assert outcome.merged_fact_count == 0

    def test_one_name_twice_is_not_a_collision(self):
        """Two elements with the identical name is a duplicate, not two
        spellings, and there is nothing for a person to decide about it."""

        assert collisions(["cart", "cart"]) == {}

    def test_collisions_are_grouped_and_sorted_so_two_runs_agree(self):
        found = collisions(["PaymentService", "payment-service", "paymentservice", "cart"])

        assert found == {
            "payment": ("PaymentService", "payment-service", "paymentservice")
        }

    def test_the_recorded_snapshot_has_no_collisions(self):
        """The subject system the demonstration runs on, checked rather than
        assumed - a collision there would change what the demo shows."""

        from app.core.config import settings
        from app.infrastructure.recovery_gateway import SnapshotFileReader

        for release in ("v0.9.0", "v0.10.0"):
            outcome = ObservationNormalizationService().normalise(
                SnapshotFileReader(settings.snapshot_root).read("online-boutique", release)
            )

            assert outcome.identity_collisions == (), release
            assert outcome.merged_fact_count == 0, release


class TestReleaseOrdering:
    """The one failure in this component that would be silent.

    Every other mistake here raises, drops a fact or shows up as a wrong
    count. An ordering that runs backwards produces a complete, plausible
    result in which a superseded decision governs a release it was replaced
    before - which is the single claim the component exists to make.
    """

    def test_a_text_comparison_of_the_demonstration_releases_is_wrong(self):
        """Stated as a test so the reason for the module is not folklore.

        If this ever starts failing, Python has changed and the rest of this
        class can go.
        """

        assert "v0.10.0" < "v0.9.0"

    def test_v0_10_0_sorts_after_v0_9_0(self):
        assert release_sort_key("v0.10.0") > release_sort_key("v0.9.0")

    def test_the_leading_v_of_a_tag_is_optional(self):
        assert release_sort_key("v0.9.0") == release_sort_key("0.9.0")

    def test_a_shortened_identifier_equals_its_full_form(self):
        """`1.0` and `1.0.0` are the same release, so the key must not make
        one of them the earlier."""

        assert release_sort_key("1.0") == release_sort_key("1.0.0")

    def test_a_release_candidate_sorts_below_the_release(self):
        assert release_sort_key("v1.0.0rc1") < release_sort_key("v1.0.0")
        assert release_sort_key("v1.0.0") < release_sort_key("v1.0.0.post1")

    def test_the_key_orders_exactly_as_the_parser_it_is_built_from(self):
        """The key is a tuple of integers rather than a version object,
        because it has to serialise and to order inside SQL. This is the test
        that the hand-built tuple did not lose any of the ordering it was
        derived from."""

        from packaging.version import Version

        identifiers = [
            "0.9.0",
            "0.10.0",
            "1.0.dev1",
            "1.0a1",
            "1.0rc1",
            "1.0",
            "1.0.post1",
            "1.0.1",
            "1.1",
            "2.0",
        ]

        assert sorted(identifiers, key=release_sort_key) == sorted(
            identifiers, key=Version
        )

    def test_an_unorderable_release_raises_and_names_itself(self):
        """A date-stamped or labelled release is refused, not guessed at.

        The message carries the identifier, because the caller's next question
        is always which one."""

        with pytest.raises(UnorderableRelease, match="release-2024-Q3"):
            release_sort_key("release-2024-Q3")

    def test_more_segments_than_the_key_carries_is_refused_not_truncated(self):
        """Ordering by the first four segments of five would make two
        different releases compare equal, which is the failure this module
        exists to prevent rather than a smaller version of it."""

        overlong = ".".join(["1"] * (RELEASE_SEGMENTS + 1))

        with pytest.raises(UnorderableRelease, match="segments"):
            release_sort_key(overlong)

    def test_every_fact_carries_the_sort_key(self):
        outcome = ObservationNormalizationService().normalise(
            architecture(
                ArchitectureStyle.MICROSERVICES,
                [element("a", "frontend"), element("b", "paymentservice")],
                [relationship("a", "b", "grpc")],
                release="v0.10.0",
            )
        )

        assert outcome.release_sort_key == release_sort_key("v0.10.0")
        assert all(fact.release_sort_key == outcome.release_sort_key for fact in outcome.facts)

    def test_an_unorderable_release_stops_the_run_before_any_fact_exists(self):
        """Checked at the front of `normalise`, not per fact. A run that
        produced ten facts and then refused the eleventh would leave the
        caller holding facts that cannot be compared to anything."""

        with pytest.raises(UnorderableRelease):
            ObservationNormalizationService().normalise(
                architecture(
                    ArchitectureStyle.MICROSERVICES,
                    [element("a", "frontend"), element("b", "paymentservice")],
                    [relationship("a", "b", "grpc")],
                    release="2024-Q3-hotfix",
                )
            )
