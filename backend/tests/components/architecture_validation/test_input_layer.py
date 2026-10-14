"""Input layer tests: translation, style adapters and relationship derivation.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Covers the boundary that absorbs recovery's output and the subject system's
    architectural style.

    Two tests here carry more weight than the rest. The event-driven collapse
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
    fact_id,
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
    RecoveredArchitecture,
    RecoveryProvenance,
)
from app.infrastructure.recovered_architecture.inventory_schema import (
    InventoryFieldError,
    InventoryVersionError,
)
from app.infrastructure.recovered_architecture.translation import (
    infer_style,
    manifest_paths,
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


def architecture(style, elements, relationships, release=RELEASE):
    return RecoveredArchitecture(
        repository_id="online-boutique",
        release_id=release,
        style=style,
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


class TestStyleInference:
    """What the inventory can and cannot establish."""

    def test_two_deployed_services_with_manifests_is_microservices(self):
        result = do_translate()

        assert result.style is ArchitectureStyle.MICROSERVICES

    def test_layer_named_components_are_layered(self):
        document = inventory(
            components=[
                {"id": "m:p", "name": "PresentationLayer", "kind": "build_unit", "confidence": "confirmed"},
                {"id": "m:d", "name": "DomainLayer", "kind": "build_unit", "confidence": "confirmed"},
            ],
            files=[],
        )

        assert do_translate(document).style is ArchitectureStyle.LAYERED

    def test_a_single_element_is_a_monolith(self):
        document = inventory(
            components=[
                {"id": "m:app", "name": "app", "kind": "build_unit", "confidence": "confirmed"}
            ],
            files=[],
        )

        assert do_translate(document).style is ArchitectureStyle.MONOLITH

    def test_event_driven_is_never_inferred(self):
        """The inventory supplies no broker and no publish/subscribe evidence,
        so claiming the style would be a guess."""

        document = inventory(
            components=[
                {"id": "s:a", "name": "a", "kind": "build_unit", "confidence": "confirmed"},
                {"id": "s:b", "name": "b", "kind": "build_unit", "confidence": "confirmed"},
            ],
            files=[],
        )

        assert infer_style(document, do_translate(document).elements) is not (
            ArchitectureStyle.EVENT_DRIVEN
        )

    def test_a_caller_who_knows_the_style_can_override_the_inference(self):
        result = do_translate(style_override=ArchitectureStyle.EVENT_DRIVEN)

        assert result.style is ArchitectureStyle.EVENT_DRIVEN


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
        assert facts[0].subject == "alpha"
        assert facts[0].object == "beta"
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

    def test_a_relationship_naming_an_unknown_element_is_dropped_with_a_warning(self):
        given = architecture(
            ArchitectureStyle.MICROSERVICES,
            [element("a", "alpha")],
            [relationship("a", "ghost", "http")],
        )

        outcome = ObservationNormalizationService().normalise(given)

        assert outcome.facts == ()
        assert any("unknown element" in warning for warning in outcome.warnings)

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
        assert facts[0].subject == "OrderComponent"
        assert facts[0].object == "PaymentComponent"
        assert facts[0].relationship is RelationshipKind.COMMUNICATES_WITH

    def test_the_channel_survives_as_an_attribute_not_as_an_element(self):
        facts = adapter_for(ArchitectureStyle.EVENT_DRIVEN).normalise(self.two_hop())

        assert facts[0].attributes["via"] == "order-events"
        assert facts[0].attributes["interaction"] == "async"
        assert facts[0].attributes["collapsed_hops"] == 2
        assert "order-events" not in {facts[0].subject, facts[0].object}

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
        synchronous = next(f for f in facts if f.object == "AuditComponent")
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


class TestRelationshipDerivation:
    """Filling in what recovery does not yet report."""

    class StubReader:
        """A source artifact reader over in-memory manifests."""

        def __init__(self, files: dict[str, str]) -> None:
            self.files = files
            self.reads: list[str] = []

        def read_text(self, repository_id, release_id, path):
            self.reads.append(path)
            return self.files[path]

        def list_paths(self, repository_id, release_id, pattern):
            return sorted(self.files)

    MANIFEST = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: checkoutservice
spec:
  template:
    spec:
      containers:
        - name: server
          env:
            - name: PAYMENT_SERVICE_ADDR
              value: "paymentservice:50051"
            - name: CART_SERVICE_ADDR
              value: "cartservice:7070"
            - name: DISABLE_PROFILER
              value: "1"
            - name: SECRET_THING
              valueFrom:
                secretKeyRef:
                  name: whatever
                  key: whatever
"""

    def given_no_relationships(self):
        return architecture(
            ArchitectureStyle.MICROSERVICES,
            [
                element("svc:checkoutservice", "checkoutservice"),
                element("svc:paymentservice", "paymentservice"),
                element("svc:cartservice", "cartservice"),
            ],
            [],
        )

    def test_declared_addresses_become_relationships(self):
        reader = self.StubReader({"kustomize/base/checkout.yaml": self.MANIFEST})

        outcome = ObservationNormalizationService(reader).normalise(
            self.given_no_relationships(), manifest_paths=("kustomize/base/checkout.yaml",)
        )

        assert outcome.derived_relationships == 2
        assert {(f.subject, f.object) for f in outcome.facts} == {
            ("checkoutservice", "paymentservice"),
            ("checkoutservice", "cartservice"),
        }

    def test_a_derived_relationship_is_confirmed_but_marked_unobserved(self):
        """Two separate axes, deliberately not collapsed into one field.

        Evidence quality asks whether an artifact names the thing - a declared
        address does, so this is confirmed in recovery's own sense. Observation
        mode asks whether the call was seen, and it was not.

        Collapsing them would cap every manifest-derived relationship at review
        and leave the component unable to report a violation about any
        repository whose runtime is not instrumented.
        """

        reader = self.StubReader({"kustomize/base/checkout.yaml": self.MANIFEST})

        outcome = ObservationNormalizationService(reader).normalise(
            self.given_no_relationships(), manifest_paths=("kustomize/base/checkout.yaml",)
        )

        fact = next(f for f in outcome.facts if f.object == "paymentservice")
        assert fact.quality == EvidenceQuality.CONFIRMED
        assert fact.attributes["observed"] is False
        assert fact.attributes["declared_via"] == "PAYMENT_SERVICE_ADDR"

    def test_the_transport_comes_from_the_port_when_there_is_no_scheme(self):
        reader = self.StubReader({"m.yaml": self.MANIFEST})

        outcome = ObservationNormalizationService(reader).normalise(
            self.given_no_relationships(), manifest_paths=("m.yaml",)
        )

        fact = next(f for f in outcome.facts if f.object == "paymentservice")
        assert fact.attributes["observed_as"] == "grpc"

    def test_an_unrecognised_port_is_not_given_an_invented_transport(self):
        reader = self.StubReader({"m.yaml": self.MANIFEST})

        outcome = ObservationNormalizationService(reader).normalise(
            self.given_no_relationships(), manifest_paths=("m.yaml",)
        )

        fact = next(f for f in outcome.facts if f.object == "cartservice")
        assert fact.attributes["observed_as"] == "declared"

    def test_a_value_sourced_from_a_secret_produces_no_relationship(self):
        reader = self.StubReader({"m.yaml": self.MANIFEST})

        outcome = ObservationNormalizationService(reader).normalise(
            self.given_no_relationships(), manifest_paths=("m.yaml",)
        )

        assert all("SECRET" not in f.attributes.get("declared_via", "") for f in outcome.facts)

    def test_an_address_naming_an_unknown_service_is_ignored(self):
        """Inventing elements here would put things in the graph recovery never
        found."""

        manifest = self.MANIFEST.replace("paymentservice:50051", "some-external-thing:443")
        reader = self.StubReader({"m.yaml": manifest})

        outcome = ObservationNormalizationService(reader).normalise(
            self.given_no_relationships(), manifest_paths=("m.yaml",)
        )

        assert {f.object for f in outcome.facts} == {"cartservice"}

    def test_derivation_is_skipped_when_recovery_already_supplied_relationships(self):
        """So it retires itself the day recovery starts reporting them."""

        reader = self.StubReader({"m.yaml": self.MANIFEST})
        given = architecture(
            ArchitectureStyle.MICROSERVICES,
            [element("a", "alpha"), element("b", "beta")],
            [relationship("a", "b", "http")],
        )

        outcome = ObservationNormalizationService(reader).normalise(
            given, manifest_paths=("m.yaml",)
        )

        assert outcome.derived_relationships == 0
        assert reader.reads == []

    def test_an_unreadable_manifest_warns_rather_than_under_reporting_silently(self):
        class FailingReader(self.StubReader):
            def read_text(self, repository_id, release_id, path):
                raise RuntimeError("clone was removed")

        outcome = ObservationNormalizationService(FailingReader({"m.yaml": ""})).normalise(
            self.given_no_relationships(), manifest_paths=("m.yaml",)
        )

        assert outcome.facts == ()
        assert any("could not read manifest" in warning for warning in outcome.warnings)

    def test_malformed_yaml_warns_rather_than_raising(self):
        reader = self.StubReader({"m.yaml": "{{ not: valid: yaml"})

        outcome = ObservationNormalizationService(reader).normalise(
            self.given_no_relationships(), manifest_paths=("m.yaml",)
        )

        assert any("could not parse manifest" in warning for warning in outcome.warnings)

    def test_no_reader_is_reported_rather_than_crashing(self):
        outcome = ObservationNormalizationService(None).normalise(
            self.given_no_relationships(), manifest_paths=("m.yaml",)
        )

        assert outcome.facts == ()
        assert any("could not be derived" in warning for warning in outcome.warnings)

    def test_derivation_is_deterministic_across_runs(self):
        """The fixture diff is how a recovery change gets noticed, so the same
        input has to produce the same bytes."""

        reader = self.StubReader({"m.yaml": self.MANIFEST})
        service = ObservationNormalizationService(reader)

        first = service.normalise(self.given_no_relationships(), manifest_paths=("m.yaml",))
        second = service.normalise(self.given_no_relationships(), manifest_paths=("m.yaml",))

        assert [f.fact_id for f in first.facts] == [f.fact_id for f in second.facts]
