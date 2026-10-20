"""Workspace artifact reader tests.

Author: Aman Mohamed M.A
Date: 2026-10-14
Description:
    Checks the reader against the layout ingestion actually produces, and
    checks the two situations it exists to distinguish: a repository that is
    not in the workspace, and a path that tries to leave the checkout.

    The first matters because the workspace is temporary. An empty read would
    look exactly like a repository that declares nothing, and validation would
    then report a clean architecture instead of an unavailable one.
"""

from pathlib import Path

import pytest

from app.infrastructure.git.workspace_artifact_reader import (
    ArtifactUnavailableError,
    WorkspaceArtifactReader,
)

CHECKOUT = "source"
REPOSITORY_KEY = "microservices-demo-58a841308994"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A workspace laid out the way ingestion lays one out."""

    checkout = tmp_path / "online-boutique" / CHECKOUT
    (checkout / "kustomize" / "base").mkdir(parents=True)
    (checkout / "kustomize" / "base" / "checkout.yaml").write_text(
        "kind: Deployment\n", encoding="utf-8"
    )
    (checkout / "kustomize" / "base" / "payment.yaml").write_text(
        "kind: Deployment\n", encoding="utf-8"
    )

    # Written beside the checkout, not inside it: this is what recovery writes
    # about the tree, and it must not appear as part of the tree.
    (tmp_path / "online-boutique" / "repository_inventory.json").write_text(
        "{}", encoding="utf-8"
    )
    return tmp_path


def reader(root: Path) -> WorkspaceArtifactReader:
    return WorkspaceArtifactReader(root, checkout_subdirectory=CHECKOUT)


class TestReadingTheCheckout:
    def test_a_repository_relative_path_is_read_from_inside_the_checkout(self, workspace):
        content = reader(workspace).read_text(
            "online-boutique", "v0.10.0", "kustomize/base/checkout.yaml"
        )

        assert content == "kind: Deployment\n"

    def test_paths_are_listed_relative_to_the_checkout_with_forward_slashes(
        self, workspace
    ):
        """The paths go on to be compared with paths from an inventory, which
        records them this way whatever platform produced them."""

        paths = reader(workspace).list_paths(
            "online-boutique", "v0.10.0", "kustomize/base/*.yaml"
        )

        assert paths == ["kustomize/base/checkout.yaml", "kustomize/base/payment.yaml"]

    def test_what_recovery_writes_about_the_tree_is_not_part_of_the_tree(self, workspace):
        with pytest.raises(ArtifactUnavailableError):
            reader(workspace).read_text(
                "online-boutique", "v0.10.0", "repository_inventory.json"
            )

    def test_without_a_subdirectory_the_checkout_is_the_repository_directory(
        self, tmp_path
    ):
        """The parameter is the caller's knowledge of a layout, so the reader
        still works for a workspace that has none."""

        (tmp_path / "flat").mkdir()
        (tmp_path / "flat" / "main.yaml").write_text("kind: Service\n", encoding="utf-8")

        assert (
            WorkspaceArtifactReader(tmp_path).read_text("flat", "v1", "main.yaml")
            == "kind: Service\n"
        )


class TestWhenTheWorkspaceCannotServe:
    def test_a_repository_that_was_never_ingested_says_so(self, workspace):
        with pytest.raises(ArtifactUnavailableError, match="Ingest it first"):
            reader(workspace).read_text("absent", "v0.10.0", "kustomize/base/checkout.yaml")

    def test_a_removed_clone_raises_rather_than_reading_nothing(self, workspace):
        with pytest.raises(ArtifactUnavailableError, match="re-ingest"):
            reader(workspace).read_text("online-boutique", "v0.10.0", "gone.yaml")

    def test_a_path_leaving_the_checkout_is_refused(self, workspace):
        """Manifest paths come from a cloned third-party repository, so they
        are data rather than something to trust."""

        with pytest.raises(ArtifactUnavailableError, match="outside the checkout"):
            reader(workspace).read_text(
                "online-boutique", "v0.10.0", "../repository_inventory.json"
            )

    def test_a_file_that_is_not_text_is_refused_clearly(self, workspace):
        (workspace / "online-boutique" / CHECKOUT / "logo.png").write_bytes(
            b"\x89PNG\r\n\x1a\n\xff\xfe"
        )

        with pytest.raises(ArtifactUnavailableError, match="not UTF-8"):
            reader(workspace).read_text("online-boutique", "v0.10.0", "logo.png")


def release_workspace(root: Path, releases: tuple[str, ...]) -> Path:
    """A workspace the way release-aware ingestion lays one out.

    Each release is its own directory - keyed by revision - and both share one
    `repository_id`, which is the identity the graph and validation use. The
    directory name is *not* that identity, which is the whole point of these
    tests.
    """

    for index, release in enumerate(releases):
        clone = root / f"microservices-demo-{release}"
        checkout = clone / CHECKOUT
        checkout.mkdir(parents=True)
        (checkout / "config.yaml").write_text(f"release: {release}\n", encoding="utf-8")
        (clone / "metadata.json").write_text(
            "{"
            f'"id": "microservices-demo-{release}", '
            '"url": "https://github.com/GoogleCloudPlatform/microservices-demo.git", '
            '"branch": "main", '
            f'"commit": "{"abc"[index] * 40}", '
            '"ingested_at": "2026-10-20T09:00:00+00:00", '
            f'"repository_id": "{REPOSITORY_KEY}", '
            f'"release_tag": "{release}", '
            f'"revision": "{release}"'
            "}",
            encoding="utf-8",
        )

    return root


class TestSeveralReleasesOfOneRepository:
    """Recovery keys a checkout by revision, so an id is not a directory."""

    def test_a_release_is_read_by_the_repository_key(self, tmp_path):
        """The pipeline validates by the repository's identity, not the clone's.

        Looking that identity up by concatenation found nothing, and validation
        failed with "No workspace checkout" after recovery had succeeded.
        """

        release_workspace(tmp_path, ("v0.9.0",))

        assert (
            reader(tmp_path).read_text(REPOSITORY_KEY, "v0.9.0", "config.yaml")
            == "release: v0.9.0\n"
        )

    def test_each_release_reads_its_own_tree(self, tmp_path):
        """Two releases of one repository are two checkouts, not one."""

        release_workspace(tmp_path, ("v0.9.0", "v0.10.6"))

        assert (
            reader(tmp_path).read_text(REPOSITORY_KEY, "v0.9.0", "config.yaml")
            == "release: v0.9.0\n"
        )
        assert (
            reader(tmp_path).read_text(REPOSITORY_KEY, "v0.10.6", "config.yaml")
            == "release: v0.10.6\n"
        )

    def test_the_clone_id_still_works(self, tmp_path):
        """Both identifiers resolve, because a caller holds whichever one it was given."""

        release_workspace(tmp_path, ("v0.9.0",))

        assert (
            reader(tmp_path).read_text(
                "microservices-demo-v0.9.0", "v0.9.0", "config.yaml"
            )
            == "release: v0.9.0\n"
        )

    def test_an_unnamed_release_is_refused_rather_than_guessed(self, tmp_path):
        """Two checkouts and no match is ambiguous, and guessing reads the
        wrong release's files while reporting it as this one's."""

        release_workspace(tmp_path, ("v0.9.0", "v0.10.6"))

        with pytest.raises(ArtifactUnavailableError, match="Ingest it first"):
            reader(tmp_path).read_text(REPOSITORY_KEY, "v9.9.9", "config.yaml")

    def test_a_lone_checkout_answers_for_a_release_the_workspace_does_not_name(
        self, tmp_path
    ):
        """A commit id rather than the tag it was ingested under is still that
        repository's only tree, so there is nothing to confuse it with."""

        release_workspace(tmp_path, ("v0.9.0",))

        assert (
            reader(tmp_path).read_text(REPOSITORY_KEY, "commit:abc123", "config.yaml")
            == "release: v0.9.0\n"
        )

    def test_paths_are_listed_from_the_release_it_was_asked_for(self, tmp_path):
        release_workspace(tmp_path, ("v0.9.0", "v0.10.6"))

        assert reader(tmp_path).list_paths(REPOSITORY_KEY, "v0.10.6", "*.yaml") == [
            "config.yaml"
        ]
