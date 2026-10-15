"""Repository scanning.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Walks a working tree and records one `FileRecord` per relevant file, with
    no file contents being read. Excluded directories are pruned before they
    are descended into, and unreadable paths are collected as warnings rather
    than aborting the scan.

    The scan is bounded on three axes - file count, file size and depth - so a
    pathological repository cannot exhaust memory or time.
"""

import os
from dataclasses import dataclass, field
from hashlib import sha1
from pathlib import Path

from app.components.architecture_recovery.repository_inventory.catalog import (
    InventoryOptions,
)
from app.components.architecture_recovery.repository_inventory.errors import (
    InventoryScanError,
)
from app.components.architecture_recovery.repository_inventory.models import (
    FileRecord,
)

# Warnings are capped: a repository with thousands of oversized or unreadable
# files should not produce an unbounded JSON document.
MAX_WARNINGS = 200


@dataclass
class ScanResult:
    """Outcome of one scan, including everything that was skipped."""

    files: list[FileRecord] = field(default_factory=list)
    excluded_file_count: int = 0
    excluded_directory_count: int = 0
    unreadable_count: int = 0
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)


def build_file_id(relative_path: str) -> str:
    """Derive a deterministic file id from the relative path.

    Hashing the path (rather than using a sequence number) keeps ids stable
    across runs, which lets inventories from two releases be compared and lets
    the graph layer merge nodes instead of duplicating them.
    """

    digest = sha1(relative_path.encode("utf-8")).hexdigest()[:12]
    return f"file:{digest}"


class RepositoryScanner:
    """Recursively inventories the files under a root directory."""

    def __init__(self, root: Path, options: InventoryOptions | None = None) -> None:
        """Bind the scanner to a root directory and a set of scan options."""

        self._root = Path(root)
        self._options = options or InventoryOptions()
        self._result = ScanResult()

    def scan(self) -> ScanResult:
        """Walk the root and return every relevant file.

        Raises `InventoryScanError` when the root is missing or not a
        directory.
        """

        if not self._root.is_dir():
            raise InventoryScanError(
                f"Inventory root is not a directory: {self._root}"
            )

        self._result = ScanResult()
        self._visit(self._root, depth=0)

        # Sort by path so the output is deterministic and diffable.
        self._result.files.sort(key=lambda item: item.path)
        return self._result

    def _visit(self, directory: Path, depth: int) -> None:
        """Record the files in `directory` and recurse into its subdirectories."""

        if self._result.truncated:
            return

        # `depth` is the number of path components above this directory, so a
        # file directly inside a directory at `depth` has `depth + 1`
        # components. Pruning here makes `max_depth` the maximum number of path
        # components a recorded file may have.
        if depth >= self._options.max_depth:
            self._result.excluded_directory_count += 1
            self._warn(
                f"skipped '{self._relative(directory)}': depth limit "
                f"{self._options.max_depth} reached"
            )
            return

        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name.lower())
        except OSError as error:
            # A directory we cannot list is recorded and skipped, never fatal.
            self._result.unreadable_count += 1
            self._warn(f"could not list '{self._relative(directory)}': {error}")
            return

        for entry in entries:
            if self._result.truncated:
                return

            name = entry.name.lower()

            # Symlinks are not followed: they can leave the repository or form
            # cycles, and they are not real files in a checkout.
            if entry.is_symlink():
                self._result.excluded_file_count += 1
                self._warn(f"skipped symlink '{self._relative_path(entry.path)}'")
                continue

            try:
                is_directory = entry.is_dir()
            except OSError as error:
                self._result.unreadable_count += 1
                self._warn(f"could not stat '{entry.path}': {error}")
                continue

            if is_directory:
                if name in self._options.effective_excluded_directories():
                    # Pruned here, so an excluded tree is never descended into.
                    self._result.excluded_directory_count += 1
                    continue

                self._visit(Path(entry.path), depth + 1)
                continue

            self._record_file(entry, name, depth + 1)

    def _record_file(self, entry: os.DirEntry, name: str, depth: int) -> None:
        """Add one file to the result, or count it as excluded."""

        options = self._options

        if name in options.excluded_file_names:
            self._result.excluded_file_count += 1
            return

        if any(name.endswith(suffix) for suffix in options.excluded_file_suffixes):
            self._result.excluded_file_count += 1
            return

        try:
            size_bytes = entry.stat(follow_symlinks=False).st_size
        except OSError as error:
            self._result.unreadable_count += 1
            self._warn(f"could not stat '{entry.path}': {error}")
            return

        # Oversized files are almost always generated bundles; recording them
        # would distort the inventory and any later content analysis.
        if size_bytes > options.max_file_size_bytes:
            self._result.excluded_file_count += 1
            self._warn(
                f"skipped '{self._relative_path(entry.path)}': "
                f"{size_bytes} bytes exceeds limit {options.max_file_size_bytes}"
            )
            return

        if len(self._result.files) >= options.max_files:
            self._result.truncated = True
            self._warn(
                f"stopped after reaching the {options.max_files} file limit; "
                "this inventory is incomplete"
            )
            return

        relative_path = self._relative_path(entry.path)
        filename = Path(relative_path).name

        self._result.files.append(
            FileRecord(
                id=build_file_id(relative_path),
                path=relative_path,
                name=filename,
                extension=Path(entry.name).suffix.lower(),
                size_bytes=size_bytes,
                depth=depth,
            )
        )

    def _relative_path(self, path: str) -> str:
        """Return `path` relative to the root, using forward slashes."""

        relative = os.path.relpath(path, self._root)
        return Path(relative).as_posix()

    def _relative(self, directory: Path) -> str:
        """Return a directory path relative to the root, for messages."""

        return Path(os.path.relpath(directory, self._root)).as_posix()

    def _warn(self, message: str) -> None:
        """Append a warning, up to the configured cap."""

        if len(self._result.warnings) < MAX_WARNINGS:
            self._result.warnings.append(message)
