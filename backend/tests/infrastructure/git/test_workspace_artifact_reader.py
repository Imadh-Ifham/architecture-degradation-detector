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
