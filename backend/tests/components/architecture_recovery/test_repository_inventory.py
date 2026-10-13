"""Tests for the repository inventory module.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Covers each pipeline stage independently and then end to end against a
    fixture repository containing three services written in different
    languages, plus manifests, an API specification, a schema and documentation.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.components.architecture_recovery.repository_inventory import (
    INVENTORY_FILE_NAME,
    ComponentDetector,
    ComponentKind,
    Confidence,
    FileCategory,
    FileClassifier,
    FileRecord,
    InventoryOptions,
    InventoryScanError,
    ManifestReader,
    RepositoryInventoryService,
    RepositoryRef,
    SCHEMA_VERSION,
    build_file_id,
    component_id,
    load_inventory,
    write_inventory,
)
from app.components.architecture_recovery.repository_inventory.scanning import (
    RepositoryScanner,
)


FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "multi_service_repo"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Return a mutable copy of the multi-service fixture repository."""

    target = tmp_path / "repo"
    shutil.copytree(FIXTURE, target)
    return target


def write(root: Path, relative_path: str, content: str = "x\n") -> Path:
    """Write a file into `root`, creating parent directories as needed."""

    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def build(root: Path, **option_overrides) -> dict:
    """Inventory `root` and return the serialised document."""

    options = (
        InventoryOptions(**option_overrides) if option_overrides else None
    )
    return RepositoryInventoryService(options=options).build(root).to_dict()


def file_entry(payload: dict, path: str) -> dict:
    """Return the file record for `path`, failing the test when absent."""

    for item in payload["files"]:
        if item["path"] == path:
            return item

    raise AssertionError(f"{path} not found in inventory files")


def component_named(payload: dict, name: str) -> dict:
    """Return the component with the given name, failing the test when absent."""

    for item in payload["components"]:
        if item["name"] == name:
            return item

    names = [item["name"] for item in payload["components"]]
    raise AssertionError(f"component '{name}' not found; present: {names}")


def record_for(relative_path: str, category: FileCategory, **kwargs) -> FileRecord:
    """Build a FileRecord that mirrors the pipeline's state for a stage test.

    The real pipeline classifies every file before any manifest is opened, so
    language and format are already populated. The caller's requested category
    is preserved so a stage can be tested in isolation.
    """

    record = FileRecord(
        id=build_file_id(relative_path),
        path=relative_path,
        name=Path(relative_path).name,
        extension=Path(relative_path).suffix.lower(),
        size_bytes=kwargs.pop("size_bytes", 1),
        depth=len(relative_path.split("/")),
        category=category,
        **kwargs,
    )

    FileClassifier().classify(record)
    record.category = category

    return record


# --------------------------------------------------------------------------- #
# Scanning
# --------------------------------------------------------------------------- #


def test_scan_excludes_dependency_and_generated_directories(workspace: Path) -> None:
    for directory in (
        "node_modules/left-pad",
        ".venv/lib",
        "__pycache__",
        "dist",
        ".git/objects",
        "target/debug",
    ):
        write(workspace, f"{directory}/artifact.txt")

    payload = build(workspace)
    scanned = {item["path"] for item in payload["files"]}

    assert not any("node_modules" in path for path in scanned)
    assert not any(".venv" in path for path in scanned)
    assert not any("__pycache__" in path for path in scanned)
    assert not any(path.startswith("dist/") for path in scanned)
    assert not any(".git" in path for path in scanned)
    assert not any("target" in path for path in scanned)

    assert payload["summary"]["excluded_directory_count"] >= 6


def test_scan_excludes_generated_file_names_and_suffixes(workspace: Path) -> None:
    write(workspace, "package-lock.json", "{}\n")
    write(workspace, "go.sum", "hash\n")
    write(workspace, "module.pyc", "\x00")
    write(workspace, "app.min.js", "x")

    scanned = {item["path"] for item in build(workspace)["files"]}

    assert "package-lock.json" not in scanned
    assert "go.sum" not in scanned
    assert "module.pyc" not in scanned
    assert "app.min.js" not in scanned


def test_scan_skips_oversized_files(workspace: Path) -> None:
    write(workspace, "huge.generated.go", "x" * 5000)

    payload = build(workspace, max_file_size_bytes=1000)
    scanned = {item["path"] for item in payload["files"]}

    assert "huge.generated.go" not in scanned
    assert payload["summary"]["excluded_file_count"] >= 1


def test_scan_truncates_at_the_file_limit(workspace: Path) -> None:
    payload = build(workspace, max_files=3)

    assert payload["summary"]["truncated"] is True
    assert len(payload["files"]) == 3
    assert any("incomplete" in warning for warning in payload["warnings"])


def test_scan_respects_max_depth(workspace: Path) -> None:
    payload = build(workspace, max_depth=1)

    depths = {item["depth"] for item in payload["files"]}

    # Only files directly at the repository root survive a depth limit of 1.
    assert depths == {1}


def test_scan_records_depth_as_path_component_count(workspace: Path) -> None:
    payload = build(workspace)

    for item in payload["files"]:
        assert item["depth"] == len(item["path"].split("/"))


def test_scan_reports_relative_posix_paths(workspace: Path) -> None:
    for item in build(workspace)["files"]:
        assert "\\" not in item["path"]
        assert not item["path"].startswith("/")


def test_scan_raises_when_root_is_missing(tmp_path: Path) -> None:
    with pytest.raises(InventoryScanError):
        RepositoryScanner(tmp_path / "nope").scan()


def test_scan_applies_extra_configurable_exclusions(workspace: Path) -> None:
    write(workspace, "third_party/vendored.go", "package vendored\n")

    options = InventoryOptions().with_extra_exclusions("third_party")
    payload = RepositoryInventoryService(options=options).build(workspace).to_dict()
    scanned = {item["path"] for item in payload["files"]}

    assert not any("third_party" in path for path in scanned)
    assert "third_party" in payload["scan_options"]["excluded_directories"]


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("services/cart/main.go", FileCategory.SOURCE_CODE),
        ("services/cart/go.mod", FileCategory.BUILD_MANIFEST),
        ("services/cart/cart_test.go", FileCategory.TEST),
        ("services/web-ui/package.json", FileCategory.BUILD_MANIFEST),
        ("services/web-ui/src/app.test.ts", FileCategory.TEST),
        ("services/checkout/pyproject.toml", FileCategory.BUILD_MANIFEST),
        ("services/checkout/tests/test_service.py", FileCategory.TEST),
        ("docker-compose.yaml", FileCategory.DEPLOYMENT_MANIFEST),
        ("deploy/kubernetes/cart-deployment.yaml", FileCategory.DEPLOYMENT_MANIFEST),
        ("Dockerfile", FileCategory.DEPLOYMENT_MANIFEST),
        ("api/openapi-cart.yaml", FileCategory.API_SPECIFICATION),
        ("db/schema.sql", FileCategory.DATABASE_SCHEMA),
        ("README.md", FileCategory.DOCUMENTATION),
        ("docs/architecture.md", FileCategory.DOCUMENTATION),
        ("main.tf", FileCategory.INFRASTRUCTURE_CONFIG),
        ("Jenkinsfile", FileCategory.INFRASTRUCTURE_CONFIG),
        ("proto/cart.proto", FileCategory.API_SPECIFICATION),
    ],
)
def test_classification_categories(path: str, expected: FileCategory) -> None:
    file = record_for(path, FileCategory.UNKNOWN)
    FileClassifier().classify(file)

    assert file.category is expected


@pytest.mark.parametrize(
    ("path", "language", "format"),
    [
        ("services/cart/main.go", "go", None),
        ("services/web-ui/src/app.ts", "typescript", None),
        ("services/checkout/src/checkout/service.py", "python", None),
        ("db/schema.sql", "sql", None),
        ("api/openapi-cart.yaml", None, "yaml"),
        ("docker-compose.yaml", None, "yaml"),
        ("Dockerfile", None, "dockerfile"),
        ("legacy/scripts/report.sh", "shell", None),
    ],
)
def test_classification_detects_language_and_format(
    path: str, language: str | None, format: str | None
) -> None:
    file = record_for(path, FileCategory.UNKNOWN)
    FileClassifier().classify(file)

    assert file.language == language
    assert file.format == format


def test_test_directory_beats_the_extension_rule() -> None:
    # `tests/helper.py` is a test by convention even though .py is source code.
    file = record_for("services/checkout/tests/helper.py", FileCategory.UNKNOWN)
    classification = FileClassifier().classify(file)

    assert file.category is FileCategory.TEST
    assert classification.rule == "path:tests"


def test_source_code_under_a_deploy_directory_stays_source_code() -> None:
    # Weak path conventions must not override a detected language.
    file = record_for("deploy/tooling/rollout.go", FileCategory.UNKNOWN)
    FileClassifier().classify(file)

    assert file.category is FileCategory.SOURCE_CODE


def test_unrecognised_structured_config_is_inferred() -> None:
    file = record_for("config/settings.json", FileCategory.UNKNOWN)
    classification = FileClassifier().classify(file)

    assert file.category is FileCategory.INFRASTRUCTURE_CONFIG
    assert classification.confidence is Confidence.INFERRED


def test_unknown_extension_is_reported_as_unknown() -> None:
    file = record_for("assets/blob.bin", FileCategory.UNKNOWN)
    FileClassifier().classify(file)

    assert file.category is FileCategory.UNKNOWN


# --------------------------------------------------------------------------- #
# Manifest inspection
# --------------------------------------------------------------------------- #


def analyse(root: Path, relative_path: str, category: FileCategory, content: str):
    """Write a manifest into `root` and run the reader over it."""

    path = write(root, relative_path, content)
    return ManifestReader().analyse(record_for(relative_path, category), path)


@pytest.mark.parametrize(
    ("path", "content", "expected"),
    [
        ("go.mod", "module github.com/example/cart\n", "github.com/example/cart"),
        ("package.json", '{"name": "web-ui"}', "web-ui"),
        ("composer.json", '{"name": "acme/orders"}', "acme/orders"),
        ("Cargo.toml", '[package]\nname = "orders"\n', "orders"),
        ("pubspec.yaml", "name: mobile\n", "mobile"),
        ("build.sbt", 'name := "orders-core"\n', "orders-core"),
        ("mix.exs", "def project do\n  app: :orders\nend\n", "orders"),
        ("pyproject.toml", '[project]\nname = "checkout"\n', "checkout"),
        (
            "pyproject.toml",
            '[tool.poetry]\nname = "checkout"\n',
            "checkout",
        ),
        ("build.gradle", "rootProject.name = 'orders'\n", "orders"),
        (
            "pom.xml",
            '<project xmlns="http://maven.apache.org/POM/4.0.0">'
            "<artifactId>orders</artifactId></project>",
            "orders",
        ),
        (
            "Orders.csproj",
            "<Project><PropertyGroup><AssemblyName>Orders</AssemblyName>"
            "</PropertyGroup></Project>",
            "Orders",
        ),
    ],
)
def test_build_manifest_declares_its_name(
    tmp_path: Path, path: str, content: str, expected: str
) -> None:
    analysis = analyse(tmp_path, path, FileCategory.BUILD_MANIFEST, content)

    assert analysis.declared_name == expected
    assert analysis.warning is None


def test_compose_manifest_declares_its_services(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "docker-compose.yaml",
        "services:\n  cart:\n    build: ./cart\n  checkout:\n    build: ./checkout\n",
    )
    analysis = ManifestReader().analyse(
        record_for("docker-compose.yaml", FileCategory.DEPLOYMENT_MANIFEST), path
    )

    assert analysis.service_names == ("cart", "checkout")


def test_kubernetes_manifest_declares_its_workload(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "cart-deployment.yaml",
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: cart\n",
    )
    analysis = ManifestReader().analyse(
        record_for("cart-deployment.yaml", FileCategory.DEPLOYMENT_MANIFEST), path
    )

    assert analysis.service_names == ("cart",)


def test_kubernetes_manifest_ignores_bare_pods(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "debug.yaml",
        "kind: Pod\nmetadata:\n  name: throwaway\n",
    )
    analysis = ManifestReader().analyse(
        record_for("debug.yaml", FileCategory.DEPLOYMENT_MANIFEST), path
    )

    assert analysis.service_names == ()


def test_multi_document_manifest_yields_every_service(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "all-deployments.yaml",
        "kind: Deployment\nmetadata:\n  name: cart\n---\n"
        "kind: Service\nmetadata:\n  name: cart-api\n",
    )
    analysis = ManifestReader().analyse(
        record_for("all-deployments.yaml", FileCategory.DEPLOYMENT_MANIFEST), path
    )

    assert analysis.service_names == ("cart", "cart-api")


def test_procfile_declares_its_process_types(tmp_path: Path) -> None:
    path = write(tmp_path, "Procfile", "web: gunicorn app:app\nworker: celery\n")
    analysis = ManifestReader().analyse(
        record_for("Procfile", FileCategory.DEPLOYMENT_MANIFEST), path
    )

    assert analysis.service_names == ("web", "worker")


def test_malformed_manifest_warns_instead_of_raising(tmp_path: Path) -> None:
    path = write(tmp_path, "package.json", "{ not json")
    analysis = ManifestReader().analyse(
        record_for("package.json", FileCategory.BUILD_MANIFEST), path
    )

    assert analysis.declared_name is None
    assert analysis.warning is not None


def test_malformed_yaml_manifest_warns_instead_of_raising(tmp_path: Path) -> None:
    path = write(tmp_path, "broken-deployment.yaml", "a: [unterminated\n")
    analysis = ManifestReader().analyse(
        record_for("broken-deployment.yaml", FileCategory.DEPLOYMENT_MANIFEST), path
    )

    assert analysis.warning is not None


def test_oversized_manifest_is_not_read(tmp_path: Path) -> None:
    path = write(tmp_path, "go.mod", "module " + "x" * 500 + "\n")
    analysis = ManifestReader(max_bytes=32).analyse(
        record_for("go.mod", FileCategory.BUILD_MANIFEST), path
    )

    assert analysis.declared_name is None
    assert analysis.warning is not None


def test_only_manifests_are_opened_for_content(workspace: Path) -> None:
    """A source file that happens to contain a name must not be read."""

    write(workspace, "services/cart/trap.go", '{"name": "not-a-manifest"}\n')

    payload = build(workspace)
    names = {item["name"] for item in payload["components"]}

    assert "not-a-manifest" not in names


# --------------------------------------------------------------------------- #
# Component detection
# --------------------------------------------------------------------------- #


def test_build_units_are_confirmed_from_their_manifests(workspace: Path) -> None:
    payload = build(workspace)

    for name, root in (
        ("cart", "services/cart"),
        ("checkout", "services/checkout"),
        ("web-ui", "services/web-ui"),
    ):
        component = component_named(payload, name)

        assert component["kind"] == ComponentKind.BUILD_UNIT.value
        assert component["confidence"] == Confidence.CONFIRMED.value
        assert component["root_path"] == root
        assert any(
            evidence["type"] == "manifest_content"
            for evidence in component["evidence"]
        )


def test_namespaced_module_name_is_reduced_to_its_last_segment(
    workspace: Path,
) -> None:
    # go.mod declares `github.com/example/cart`; the service-like name is `cart`.
    payload = build(workspace)
    cart = component_named(payload, "cart")

    assert any(
        "github.com/example/cart" in evidence["detail"]
        for evidence in cart["evidence"]
    )


def test_every_declared_service_matches_a_build_unit(workspace: Path) -> None:
    """Deployment names must reconcile with code units, not duplicate them."""

    payload = build(workspace)
    kinds = {item["kind"] for item in payload["components"]}

    assert ComponentKind.DEPLOYMENT_SERVICE.value not in kinds


def test_directory_without_a_manifest_is_only_a_candidate(workspace: Path) -> None:
    payload = build(workspace)
    scripts = component_named(payload, "scripts")

    assert scripts["kind"] == ComponentKind.DIRECTORY_GROUP.value
    # Directory proximity alone is never promoted to a confirmed boundary.
    assert scripts["confidence"] == Confidence.INFERRED.value
    assert scripts["root_path"] == "legacy/scripts"


def test_undeclared_deployment_service_creates_a_component_with_a_warning(
    workspace: Path,
) -> None:
    write(
        workspace,
        "deploy/kubernetes/payments-deployment.yaml",
        "kind: Deployment\nmetadata:\n  name: payments\n",
    )

    payload = build(workspace)
    payments = component_named(payload, "payments")

    assert payments["kind"] == ComponentKind.DEPLOYMENT_SERVICE.value
    assert payments["confidence"] == Confidence.CONFIRMED.value
    # The manifest names the service but not where its code lives.
    assert payments["root_path"] is None
    assert any("payments" in warning for warning in payload["warnings"])


def test_directory_group_is_not_created_inside_a_build_unit() -> None:
    files = [
        record_for("services/cart/go.mod", FileCategory.BUILD_MANIFEST),
        record_for("services/cart/main.go", FileCategory.SOURCE_CODE),
        record_for("services/cart/internal/handlers.go", FileCategory.SOURCE_CODE),
    ]

    result = ComponentDetector().detect(files, {})

    roots = {item.root_path for item in result.components}

    assert roots == {"services/cart"}


def test_files_are_assigned_to_the_deepest_component(workspace: Path) -> None:
    payload = build(workspace)

    assert file_entry(payload, "services/cart/main.go")["component_id"] == (
        component_named(payload, "cart")["id"]
    )
    assert file_entry(payload, "legacy/scripts/report.sh")["component_id"] == (
        component_named(payload, "scripts")["id"]
    )


def test_component_file_counts_and_languages_are_reported(workspace: Path) -> None:
    payload = build(workspace)
    cart = component_named(payload, "cart")

    assert cart["file_count"] == 4
    assert cart["languages"] == ["go"]


# --------------------------------------------------------------------------- #
# Relationships
# --------------------------------------------------------------------------- #


def relationships_of(payload: dict, relationship_type: str) -> list[dict]:
    return [
        item for item in payload["relationships"] if item["type"] == relationship_type
    ]


def test_file_membership_inherits_component_confidence(workspace: Path) -> None:
    payload = build(workspace)
    memberships = relationships_of(payload, "file_in_component")

    by_source = {item["source"]["id"]: item for item in memberships}

    confirmed = by_source[file_entry(payload, "services/cart/main.go")["id"]]
    inferred = by_source[file_entry(payload, "legacy/scripts/report.sh")["id"]]

    assert confirmed["confidence"] == Confidence.CONFIRMED.value
    assert inferred["confidence"] == Confidence.INFERRED.value


def test_build_manifest_defines_its_component(workspace: Path) -> None:
    payload = build(workspace)
    links = relationships_of(payload, "manifest_defines_component")

    sources = {item["source"]["id"] for item in links}

    assert file_entry(payload, "services/cart/go.mod")["id"] in sources
    assert all(item["confidence"] == Confidence.CONFIRMED.value for item in links)


def test_deployment_manifest_references_its_service(workspace: Path) -> None:
    payload = build(workspace)
    links = relationships_of(payload, "deployment_references_component")

    targets = {item["target"]["id"] for item in links}

    assert component_named(payload, "cart")["id"] in targets
    assert component_named(payload, "checkout")["id"] in targets
    # The manifests sit outside the units they name, so this stays inferred.
    assert all(item["confidence"] == Confidence.INFERRED.value for item in links)


def test_deployment_inside_the_component_is_confirmed(workspace: Path) -> None:
    write(
        workspace,
        "services/cart/deploy/cart-service.yaml",
        "kind: Deployment\nmetadata:\n  name: cart\n",
    )

    payload = build(workspace)
    cart_id = component_named(payload, "cart")["id"]

    link = next(
        item
        for item in relationships_of(payload, "deployment_references_component")
        if item["target"]["id"] == cart_id
        and item["source"]["id"]
        == file_entry(payload, "services/cart/deploy/cart-service.yaml")["id"]
    )

    assert link["confidence"] == Confidence.CONFIRMED.value
    assert link["evidence"][0]["type"] == "deployment_manifest"


def test_deployment_evidence_upgrades_a_directory_group(workspace: Path) -> None:
    write(
        workspace,
        "legacy/scripts/report-deployment.yaml",
        "kind: Deployment\nmetadata:\n  name: scripts\n",
    )

    payload = build(workspace)
    scripts = component_named(payload, "scripts")

    assert any(
        evidence["type"] == "deployment_manifest"
        for evidence in scripts["evidence"]
    )


def test_api_specification_is_associated_with_a_component(workspace: Path) -> None:
    payload = build(workspace)
    links = relationships_of(payload, "api_spec_describes_component")

    assert len(links) == 1
    assert links[0]["source"]["id"] == (
        file_entry(payload, "api/openapi-cart.yaml")["id"]
    )
    assert links[0]["target"]["id"] == component_named(payload, "cart")["id"]
    assert links[0]["confidence"] == Confidence.INFERRED.value


def test_test_file_targets_its_component(workspace: Path) -> None:
    payload = build(workspace)
    links = relationships_of(payload, "test_targets_component")
    sources = {item["source"]["id"] for item in links}

    assert file_entry(payload, "services/cart/cart_test.go")["id"] in sources
    assert file_entry(payload, "services/web-ui/src/app.test.ts")["id"] in sources


def test_relationship_ids_are_deterministic_and_unique(workspace: Path) -> None:
    payload = build(workspace)
    identifiers = [item["id"] for item in payload["relationships"]]

    assert len(identifiers) == len(set(identifiers))


# --------------------------------------------------------------------------- #
# Output document
# --------------------------------------------------------------------------- #


def test_inventory_document_structure(workspace: Path) -> None:
    payload = build(workspace)

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["generator"]["name"] == "repository_inventory"
    assert payload["repository"] == {
        "id": None,
        "url": None,
        "branch": None,
        "commit": None,
    }
    assert set(
        ("files", "classifications", "components", "relationships")
    ).issubset(payload)

    # Classifications are a separate collection keyed by file id.
    file_ids = {item["id"] for item in payload["files"]}
    assert {item["file_id"] for item in payload["classifications"]} == file_ids


def test_summary_reports_categories_and_languages(workspace: Path) -> None:
    summary = build(workspace)["summary"]

    assert summary["file_count"] == 20
    assert summary["truncated"] is False
    assert set(summary["by_language"]) == {
        "go",
        "python",
        "typescript",
        "sql",
        "shell",
    }
    assert summary["by_category"]["build_manifest"] == 3
    assert summary["by_category"]["deployment_manifest"] == 3
    assert summary["component_count"] == 4


def test_inventory_is_deterministic(workspace: Path) -> None:
    first = build(workspace)
    second = build(workspace)

    first.pop("generated_at")
    second.pop("generated_at")

    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_writer_creates_a_single_versioned_json_file(tmp_path: Path) -> None:
    inventory = RepositoryInventoryService().build(FIXTURE, RepositoryRef(id="repo-1"))

    written = write_inventory(inventory, tmp_path)

    assert written.name == INVENTORY_FILE_NAME
    assert written.parent == tmp_path
    assert [item.name for item in tmp_path.iterdir()] == [INVENTORY_FILE_NAME]

    payload = load_inventory(written)

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["repository"]["id"] == "repo-1"


def test_writer_replaces_an_existing_inventory_atomically(tmp_path: Path) -> None:
    service = RepositoryInventoryService()

    first = write_inventory(service.build(FIXTURE), tmp_path)
    original_size = first.stat().st_size

    second = write_inventory(service.build(FIXTURE), tmp_path)

    assert first == second
    # No temporary file is left behind by the atomic replace.
    assert [item.name for item in tmp_path.iterdir()] == [INVENTORY_FILE_NAME]
    assert second.stat().st_size == original_size


def test_run_writes_beside_the_ingested_working_tree(workspace: Path) -> None:
    from app.domain.repository import IngestedRepository

    ingested = IngestedRepository(
        id="repo-1",
        url="https://example.com/team/repo.git",
        branch="main",
        commit="a" * 40,
        path=workspace,
        ingested_at=datetime.now(timezone.utc),
    )

    written, inventory = RepositoryInventoryService().run_for_ingested(ingested)

    # The inventory is a sibling of the working tree, never inside it.
    assert written.parent == workspace.parent
    assert not (workspace / INVENTORY_FILE_NAME).exists()

    payload = load_inventory(written)

    assert payload["repository"] == {
        "id": "repo-1",
        "url": "https://example.com/team/repo.git",
        "branch": "main",
        "commit": "a" * 40,
    }
    # The document is returned as well, so a caller need not read it back.
    assert inventory.repository.id == "repo-1"


def test_identifiers_are_stable_across_runs() -> None:
    assert build_file_id("services/cart/main.go") == build_file_id(
        "services/cart/main.go"
    )
    assert build_file_id("a.go") != build_file_id("b.go")
    assert component_id(ComponentKind.BUILD_UNIT, "services/cart") == component_id(
        ComponentKind.BUILD_UNIT, "services/cart"
    )


def test_clean_fixture_produces_no_warnings(workspace: Path) -> None:
    assert build(workspace)["warnings"] == []
