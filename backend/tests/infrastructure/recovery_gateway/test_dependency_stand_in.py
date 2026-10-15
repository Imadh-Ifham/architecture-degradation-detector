"""Stand-in dependency production tests.

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    Checks the module that produces the element-to-element dependencies
    recovery will supply itself, and does not supply yet.

    These tests moved out of the validation component's suite along with the
    code. They belong here because what they exercise is infrastructure
    standing in for an upstream component - the validation component is no
    longer involved, and its own tests now assert that it cannot reach a file
    at all.
"""

import pytest

from app.components.architecture_validation.observation_normalization._style import (
    infer_style,
)
from app.domain.recovered_architecture import (
    ArchitectureElement,
    ArchitectureRelationship,
    ArchitectureStyle,
    DerivationMethod,
    ElementKind,
    EvidenceQuality,
    RecoveredArchitecture,
    RecoveryProvenance,
    StyleSource,
)
from app.infrastructure.recovery_gateway.c1_dependency_stand_in import (
    element_key,
    supply_dependencies,
)

RELEASE = "v0.10.0"

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


class FailingReader(StubReader):
    def read_text(self, repository_id, release_id, path):
        raise OSError("workspace is gone")


def element(identifier, name, kind=ElementKind.SERVICE, quality=EvidenceQuality.CONFIRMED):
    return ArchitectureElement(id=identifier, name=name, kind=kind, quality=quality)


def given(relationships=(), manifests=("kustomize/base/checkout.yaml",)):
    return RecoveredArchitecture(
        repository_id="online-boutique",
        release_id=RELEASE,
        style=ArchitectureStyle.MICROSERVICES,
        style_source=StyleSource.C1,
        elements=(
            element("svc:checkoutservice", "checkoutservice"),
            element("svc:paymentservice", "paymentservice"),
            element("svc:cartservice", "cartservice"),
        ),
        relationships=tuple(relationships),
        provenance=RecoveryProvenance("fixture_reader", "1.0.0", "test"),
        manifest_paths=tuple(manifests),
    )


def reader(files=None):
    return StubReader(files or {"kustomize/base/checkout.yaml": MANIFEST})


class TestProducingDependencies:
    """What the stand-in produces, and what it refuses to invent."""

    def test_declared_addresses_become_dependencies(self):
        filled, warnings = supply_dependencies(given(), reader())

        edges = {(r.source_id, r.target_id) for r in filled.relationships}
        assert edges == {
            ("svc:checkoutservice", "svc:paymentservice"),
            ("svc:checkoutservice", "svc:cartservice"),
        }
        assert warnings == ()

    def test_a_produced_dependency_is_confirmed_but_marked_unobserved(self):
        """Two axes, deliberately separate. An artifact names both ends, which
        is what recovery means by confirmed. Whether the call was seen is a
        different question, and collapsing them would cap every
        manifest-derived dependency at review - leaving the pipeline unable to
        report a violation about any repository whose runtime is not
        instrumented, which is all of them."""

        filled, _ = supply_dependencies(given(), reader())
        produced = filled.relationships[0]

        assert produced.quality is EvidenceQuality.CONFIRMED
        assert produced.derived_by is DerivationMethod.DERIVED_FROM_DEPLOYMENT
        assert produced.attributes["observed"] is False
        assert produced.attributes["declared_via"].endswith("_ADDR")

    def test_the_transport_comes_from_the_port_when_there_is_no_scheme(self):
        filled, _ = supply_dependencies(given(), reader())
        labels = {r.target_id: r.label for r in filled.relationships}

        assert labels["svc:paymentservice"] == "grpc"

    def test_an_unrecognised_port_is_not_given_an_invented_transport(self):
        filled, _ = supply_dependencies(given(), reader())
        labels = {r.target_id: r.label for r in filled.relationships}

        assert labels["svc:cartservice"] == "declared"

    def test_a_value_sourced_from_a_secret_produces_no_dependency(self):
        """A reference carries no address. Treating one as a value would
        produce a dependency on the literal string "valueFrom"."""

        filled, _ = supply_dependencies(given(), reader())

        assert len(filled.relationships) == 2

    def test_an_address_naming_an_unknown_service_is_ignored(self):
        """Inventing an element here would put something in the graph that
        recovery never found."""

        manifest = MANIFEST.replace("paymentservice:50051", "someoneelse:50051")
        filled, _ = supply_dependencies(
            given(), reader({"kustomize/base/checkout.yaml": manifest})
        )

        targets = {r.target_id for r in filled.relationships}
        assert "svc:paymentservice" not in targets

    def test_name_spellings_match_an_element(self):
        """A manifest may spell a service differently from the inventory."""

        assert element_key("payment-service") == element_key("paymentservice")
        assert element_key("PaymentService") == element_key("paymentservice")
        assert element_key("service") == "service"

    def test_production_is_deterministic_across_runs(self):
        """Sorted output is what lets the recorded snapshot's diff mean
        something."""

        first, _ = supply_dependencies(given(), reader())
        second, _ = supply_dependencies(given(), reader())

        assert first.relationships == second.relationships


class TestWhenItShouldNotRun:
    """The stand-in retires itself rather than being switched off."""

    def test_it_is_a_no_op_once_recovery_supplies_relationships(self):
        """This is how it stops being used before it is deleted: re-recording
        a release after recovery ships its own extraction changes the output
        and not this module."""

        supplied = ArchitectureRelationship(
            source_id="svc:checkoutservice",
            target_id="svc:paymentservice",
            label="grpc",
            quality=EvidenceQuality.CONFIRMED,
            derived_by=DerivationMethod.RECOVERED,
        )
        architecture = given(relationships=(supplied,))
        stub = reader()

        filled, warnings = supply_dependencies(architecture, stub)

        assert filled is architecture
        assert warnings == ()
        assert stub.reads == []

    def test_no_reader_is_reported_rather_than_crashing(self):
        filled, warnings = supply_dependencies(given(), None)

        assert filled.relationships == ()
        assert any("no artifact reader" in warning for warning in warnings)

    def test_no_manifest_paths_is_reported(self):
        filled, warnings = supply_dependencies(given(manifests=()), reader())

        assert filled.relationships == ()
        assert warnings


class TestWhenAManifestCannotBeRead:
    """An under-reported architecture looks exactly like a clean one."""

    def test_an_unreadable_manifest_warns_rather_than_under_reporting_silently(self):
        filled, warnings = supply_dependencies(
            given(), FailingReader({"kustomize/base/checkout.yaml": MANIFEST})
        )

        assert filled.relationships == ()
        assert any("could not read manifest" in warning for warning in warnings)

    def test_malformed_yaml_warns_rather_than_raising(self):
        filled, warnings = supply_dependencies(
            given(), reader({"kustomize/base/checkout.yaml": "a: [unclosed"})
        )

        assert filled.relationships == ()
        assert any("could not parse manifest" in warning for warning in warnings)


class TestAgainstTheRecordedSnapshots:
    """The recording this produces is what the component develops against."""

    @pytest.mark.parametrize("release", ["v0.9.0", "v0.10.0"])
    def test_the_recorded_snapshot_carries_dependencies(self, release):
        from app.infrastructure.recovery_gateway.snapshot_file_reader import (
            SnapshotFileReader,
        )

        from app.core.config import settings

        architecture = SnapshotFileReader(settings.snapshot_root).read(
            "online-boutique", release
        )

        assert architecture.has_element_relationships

        # The recording holds recovery's answer about the style, and recovery
        # has none yet - so it records the absence rather than C2's inference.
        # Baking the inference into the recording would make a later change to
        # the inference invisible in a diff, and would read as recovery having
        # detected something.
        assert architecture.style_source is StyleSource.INFERRED_BY_C2
        assert (
            infer_style(architecture.elements, architecture.relationships)
            is ArchitectureStyle.MICROSERVICES
        )
