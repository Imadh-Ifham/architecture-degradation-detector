"""Conformance: does recovery's output still mean what this component reads?

Author: Aman Mohamed M.A
Date: 2026-10-15
Description:
    Every other test in this component runs against a **recorded** copy of
    recovery's output, which is exactly what makes them fast and reproducible
    - and exactly what makes them blind to recovery changing.

    A frozen fixture cannot notice upstream drift. If a field is renamed, a
    confidence value is replaced or a category disappears, the recorded
    document still passes and the live one stops working. That difference
    would be discovered during integration, by whoever did not cause it.

    So this file runs **recovery's own code, as it is today**, over the
    committed subject tree, and asserts the handful of things this component
    reads out of the result. It is the only test here that imports another
    component, and that is the point: it is a contract test, and the contract
    has two sides.

    It names the fields rather than checking a schema, because the failure
    message has to say what to do. "components[].confidence is missing" sends
    somebody to one line of a conversation; "the inventory document changed"
    sends them reading.

    Recovery is free to change. This is only here so that when it does, this
    component finds out in a second rather than in a week.
"""

from pathlib import Path

import pytest

from app.components.architecture_recovery.repository_inventory.service import (
    RepositoryInventoryService,
    inventory_options_from_settings,
)
from app.infrastructure.recovery_gateway.graph_translation import (
    DECLARED_CONFIDENCES,
    ELEMENT_KINDS,
    RELATIONSHIP_LABELS,
)
from app.infrastructure.recovery_gateway.inventory_schema import (
    CONFIDENCE_CONFIRMED,
    CONFIDENCE_INFERRED,
    CONTRACT_VERSION,
    MANIFEST_CATEGORIES,
    assert_shape,
    assert_version,
)
from app.infrastructure.recovery_gateway.translation import (
    manifest_paths,
    read_style,
    translate,
)

SUBJECT = Path(__file__).resolve().parents[2] / "fixtures" / "validation" / "subject"
RELEASES = ("v0.9.0", "v0.10.0")

ELEMENTS = 12
"""Components recovery finds in the later release of the subject tree.

Asserted so that a change in how components are detected is visible here as a
number rather than as a surprise three stages later.
"""


@pytest.fixture(scope="module")
def live_documents() -> dict[str, dict]:
    """Recovery's inventory, built now, by recovery's own service."""

    service = RepositoryInventoryService(options=inventory_options_from_settings())
    return {
        release: service.build(root=SUBJECT / release).to_dict()
        for release in RELEASES
    }


class TestTheContractThisComponentReads:
    """The fields, by name, so a break says which one."""

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_document_is_the_schema_version_this_component_targets(
        self, live_documents, release
    ):
        """A version move is the one change that should stop a run rather than
        be absorbed, and it should say both versions."""

        assert live_documents[release]["schema_version"] == CONTRACT_VERSION
        assert_version(live_documents[release])

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_document_still_holds_the_sections_we_read(
        self, live_documents, release
    ):
        assert_shape(live_documents[release])

    @pytest.mark.parametrize("release", RELEASES)
    def test_every_component_carries_the_four_fields_we_use(
        self, live_documents, release
    ):
        """`id` becomes the element id a fact is traced back through, `name`
        becomes the element, `kind` decides whether it is one at all, and
        `confidence` becomes the quality that caps a verdict about it."""

        for component in live_documents[release]["components"]:
            for field in ("id", "name", "kind", "confidence"):
                assert component.get(field), f"components[].{field} is missing"

    @pytest.mark.parametrize("release", RELEASES)
    def test_confidence_is_still_one_of_the_two_values_we_handle(
        self, live_documents, release
    ):
        """A third value would silently become "not confirmed", which caps
        every verdict about that element without anybody deciding to."""

        values = {c["confidence"] for c in live_documents[release]["components"]}

        assert values <= {CONFIDENCE_CONFIRMED, CONFIDENCE_INFERRED}, values

    @pytest.mark.parametrize("release", RELEASES)
    def test_files_still_carry_the_path_category_and_component(
        self, live_documents, release
    ):
        """How the manifest paths are found, and those paths are the only
        thing the decision scan is given to read."""

        for record in live_documents[release]["files"]:
            assert "path" in record and "category" in record

        categorised = {
            record["category"] for record in live_documents[release]["files"]
        }
        assert categorised & MANIFEST_CATEGORIES, (
            "no file is in a category this component recognises as a manifest, "
            f"so the decision scan would be handed nothing. Saw: {sorted(categorised)}"
        )

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_manifests_are_located_and_the_policies_are_among_them(
        self, live_documents, release
    ):
        """The decision scan reads these paths and nothing else. If the
        policies stop being classified as manifests, the whole decision corpus
        silently becomes empty."""

        paths = manifest_paths(live_documents[release])

        assert paths
        assert any("network-polic" in path for path in paths), (
            "no network policy is classified as a manifest; the reconstructed "
            "decisions all come from these files"
        )


class TestWhatThisComponentMakesOfIt:
    """The document, through this component's own translation."""

    @pytest.mark.parametrize("release", RELEASES)
    def test_the_live_document_translates_into_an_architecture(
        self, live_documents, release
    ):
        architecture = _translated(live_documents[release], release)

        assert architecture.elements
        assert architecture.manifest_paths
        assert architecture.release_id == release

    def test_the_element_count_has_not_moved(self, live_documents):
        """A number rather than a shrug. If recovery changes how it groups
        components this fails here, with the old count and the new one."""

        architecture = _translated(live_documents["v0.10.0"], "v0.10.0")

        assert len(architecture.elements) == ELEMENTS

    @pytest.mark.parametrize("release", RELEASES)
    def test_recovery_still_detects_no_architectural_style(
        self, live_documents, release
    ):
        """The day this fails is good news: it means recovery has started
        answering the question, and this component must stop inferring it and
        take recovery's answer instead."""

        style, source = read_style(live_documents[release])

        assert style == "unknown"
        assert source == "inferred_by_c2"


class TestTheArchitectureGraphVocabulary:
    """Recovery names its own kinds, and this component maps every one.

    The inventory tests above read a document. These read recovery's
    **vocabulary** - the constants its graph construction emits - because
    that is where drift now shows up: a new relationship kind or a new
    infrastructure role appears as a word nothing here has a rule for, and
    the mapping silently falls through to its default.

    A fall-through is not loud. An unmapped relationship kind becomes a
    dependency rather than a communication, every rule written about
    communication then matches nothing, and a correct run reports the whole
    architecture as ungoverned with no error anywhere. That is the failure
    these three tests exist to turn into a red line.
    """

    def test_every_relationship_kind_has_a_label(self):
        from app.components.architecture_recovery.graph_construction.builder import (
            _DEPENDENCY_KIND,
            _FINDING_KIND,
        )

        emitted = set(_DEPENDENCY_KIND.values()) | set(_FINDING_KIND.values())
        unmapped = emitted - set(RELATIONSHIP_LABELS)

        assert not unmapped, (
            f"recovery emits relationship kind(s) {sorted(unmapped)} that this "
            "component has no label for. Add them to RELATIONSHIP_LABELS, and "
            "decide for each whether it is a communication or a dependency."
        )

    def test_every_component_and_infrastructure_kind_is_an_element_kind(self):
        from app.components.architecture_recovery.dependency_resolution.models import (
            InfrastructureKind,
        )
        from app.components.architecture_recovery.repository_inventory.models import (
            ComponentKind,
        )

        emitted = {item.value for item in ComponentKind} | {
            item.value for item in InfrastructureKind
        }

        assert not emitted - set(ELEMENT_KINDS), (
            f"recovery emits kind(s) {sorted(emitted - set(ELEMENT_KINDS))} that "
            "this component maps to nothing. Unmapped kinds become modules, "
            "which is right for a build unit and wrong for a datastore."
        )

    def test_the_confidence_that_means_declared_is_still_called_that(self):
        from app.components.architecture_recovery.component_discovery.models import (
            AssociationConfidence,
        )

        assert AssociationConfidence.DIRECT.value in DECLARED_CONFIDENCES
        assert AssociationConfidence.HEURISTIC.value not in DECLARED_CONFIDENCES


def _translated(document: dict, release: str):
    """The live document, through this component's own translation.

    The reader and the reference are the provenance a run stamps on its
    result, so a result always says which input produced it. Here they say
    the input was built during a test rather than recorded.
    """

    return translate(
        document,
        repository_id="online-boutique",
        release_id=release,
        source_reference=f"built live from {SUBJECT.name}/{release}",
        reader="conformance_test",
    )
