# Tests for commit history (C4-T12, FR-05): file filter, mining cache and files -> elements.
# End-to-end tests mine a tiny git repo with fixed dates (support.build_tiny_repo).

import datetime as dt
from collections.abc import Mapping, Sequence
from pathlib import Path

import networkx as nx
import pytest
from structlog.testing import capture_logs

from app.components.degradation_scoring.features.history import (
    FileFilter,
    apply_filter,
    load_commits,
    map_to_elements,
    split_globs,
)
from app.components.degradation_scoring.features.models import CommitRecord, FileChange
from app.components.degradation_scoring.ports import CommitHistorySource
from app.infrastructure.git.history import PyDrillerHistorySource
from tests.components.degradation_scoring.support import (
    ORDER,
    PAY,
    UTIL,
    FakeHistorySource,
    FakeMiningCache,
    build_tiny_repo,
    default_config,
    git_commit,
    init_repo,
)

CONFIG = default_config()
DEFAULT_FILTER = FileFilter.from_settings(
    CONFIG.history_include_globs, CONFIG.history_exclude_globs
)


@pytest.fixture(scope="module")
def tiny(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, str]]:
    root = tmp_path_factory.mktemp("tiny-repo")
    return root, build_tiny_repo(root)


def graph() -> "nx.DiGraph[str]":
    # order and pay both list the shared util file; ui has no paths; nobody owns src/search
    g: nx.DiGraph[str] = nx.DiGraph()
    g.add_node("order", source_paths=[ORDER, UTIL])
    g.add_node("pay", source_paths=[PAY, UTIL])
    g.add_node("ui", source_paths=[])
    g.add_edge("ui", "order", weight=1)
    return g


def commit(*paths: str, hash_: str = "h1") -> CommitRecord:
    return CommitRecord(
        hash=hash_,
        author_email="a@example.com",
        committed_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        message="m",
        files=[FileChange(path=path, added=2, deleted=1) for path in paths],
    )


class FailingSource:
    # a history source that must not be asked: the cache should answer
    def commits(self, repo_path: str, from_tag: str, to_tag: str) -> Sequence[Mapping[str, object]]:
        raise AssertionError("history source called although the range is cached")

    def tag_dates(self, repo_path: str) -> Mapping[str, str]:
        raise AssertionError("not needed here")


@pytest.mark.parametrize(
    "path",
    ["src/order/OrderService.java", "app/main.py", "web/src/app.ts", "src/cart/Cart.cs"],
)
def test_default_filter_keeps_source_files(path: str) -> None:
    assert DEFAULT_FILTER.keeps(path)


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "vendor/lib/Dep.java",
        "src/x/node_modules/y.js",
        "api/generated/Client.java",
        "proto/demo_pb2.py",
        "pb/demo.pb.go",
        "tests/fixtures/sample.py",
        "web/app.min.js",
        "target/Out.java",
        "services/billing/target/classes/A.java",
        "build/gen.py",
        "dist/bundle.js",
        "src/cartservice/bin/Cart.cs",
        "src/cartservice/obj/Debug/Cart.cs",
    ],
)
def test_default_filter_drops_non_source_and_build_output(path: str) -> None:
    # excludes match at any depth, e.g. bin/ and obj/ inside a C# service folder
    assert not DEFAULT_FILTER.keeps(path)


def test_split_globs_ignores_blanks_and_spaces() -> None:
    assert split_globs(" *.py, ,*.java,") == ("*.py", "*.java")


def test_fingerprint_ignores_glob_order_but_not_glob_content() -> None:
    a = FileFilter(("*.py", "*.java"), ("**/vendor/**",))
    b = FileFilter(("*.java", "*.py"), ("**/vendor/**",))
    c = FileFilter(("*.py",), ("**/vendor/**",))

    assert a.fingerprint == b.fingerprint
    assert a.fingerprint != c.fingerprint
    assert a.fingerprint.startswith("sha256:")


def test_apply_filter_drops_files_and_empty_commits() -> None:
    kept = apply_filter(commit(ORDER, "README.md"), DEFAULT_FILTER)

    assert kept is not None
    assert [f.path for f in kept.files] == [ORDER]
    assert apply_filter(commit("README.md"), DEFAULT_FILTER) is None


def test_mined_commits_are_the_filtered_range(tiny: tuple[Path, dict[str, str]]) -> None:
    root, hashes = tiny
    commits = load_commits(
        PyDrillerHistorySource(),
        FakeMiningCache(),
        repo_path=root,
        from_tag="v1.0.0",
        to_tag="v1.1.0",
        file_filter=DEFAULT_FILTER,
    )

    # c4 (README + vendor) has no source file left; the merge, c0 and c6 are outside
    assert [c.hash for c in commits] == [hashes[n] for n in ("c2", "c1", "c3", "c5")]
    assert [f.path for f in commits[1].files] == [ORDER]


def test_second_run_reads_the_cache(tiny: tuple[Path, dict[str, str]]) -> None:
    root, _ = tiny
    cache = FakeMiningCache()

    def run(source: CommitHistorySource) -> list[CommitRecord]:
        return load_commits(
            source,
            cache,
            repo_path=root,
            from_tag="v1.0.0",
            to_tag="v1.1.0",
            file_filter=DEFAULT_FILTER,
        )

    with capture_logs() as logs:
        first = run(PyDrillerHistorySource())
        second = run(FailingSource())

    assert second == first
    assert [entry["reason"] for entry in logs] == ["cache_miss", "cache_hit"]
    (key,) = cache.entries
    assert key == (root.resolve().as_posix(), "v1.0.0", "v1.1.0", DEFAULT_FILTER.fingerprint)


def test_other_filter_or_range_is_mined_again() -> None:
    source = FakeHistorySource([commit(ORDER).model_dump(mode="json")])
    cache = FakeMiningCache()
    repo = Path("repo")

    load_commits(
        source, cache, repo_path=repo, from_tag="a", to_tag="b", file_filter=DEFAULT_FILTER
    )
    load_commits(
        source, cache, repo_path=repo, from_tag="a", to_tag="c", file_filter=DEFAULT_FILTER
    )
    narrow = FileFilter(("*.py",), ())
    load_commits(source, cache, repo_path=repo, from_tag="a", to_tag="b", file_filter=narrow)

    assert len(source.requests) == 3
    assert source.requests[0] == (repo.resolve().as_posix(), "a", "b")
    assert cache.entries[(repo.resolve().as_posix(), "a", "b", narrow.fingerprint)] == []


def test_files_map_to_their_elements(tiny: tuple[Path, dict[str, str]]) -> None:
    root, hashes = tiny
    commits = load_commits(
        PyDrillerHistorySource(),
        FakeMiningCache(),
        repo_path=root,
        from_tag="v1.0.0",
        to_tag="v1.1.0",
        file_filter=DEFAULT_FILTER,
    )

    history = map_to_elements(commits, graph())

    # c2: pay +2; c1: order +4 -1; c3: util +4 (order and pay) and order +1; c5 owned by nobody
    assert [(c.hash, c.lines_by_element) for c in history.commits] == [
        (hashes["c2"], {"pay": 2}),
        (hashes["c1"], {"order": 5}),
        (hashes["c3"], {"order": 5, "pay": 4}),
    ]
    assert history.commits[2].files_changed == 2
    assert history.commits[2].message == "fix: null check in util"
    assert history.shared_files == [UTIL]
    assert history.unmapped_files == ["src/search/Search.py"]


def test_shared_and_unmapped_files_are_logged() -> None:
    with capture_logs() as logs:
        map_to_elements([commit(UTIL, "src/other/X.java")], graph())

    assert {(entry["reason"], entry["count"]) for entry in logs} == {
        ("file_shared", 1),
        ("file_unmapped", 1),
    }


def test_source_paths_may_be_folders_or_globs() -> None:
    g: nx.DiGraph[str] = nx.DiGraph()
    g.add_node("order", source_paths=["src/order"])
    g.add_node("pay", source_paths=["src/pay/*.java"])

    history = map_to_elements(
        [commit("src/order/sub/New.java", "src/pay/Pay.java", "src/orders/X.java")], g
    )

    assert history.commits[0].lines_by_element == {"order": 3, "pay": 3}
    assert history.unmapped_files == ["src/orders/X.java"]  # whole folder names only


def test_graph_without_paths_maps_nothing() -> None:
    g: nx.DiGraph[str] = nx.DiGraph()
    g.add_node("a")

    with capture_logs() as logs:
        history = map_to_elements([commit(ORDER)], g)

    assert history.commits == []
    assert history.unmapped_files == [ORDER]
    assert [entry["reason"] for entry in logs] == ["file_unmapped"]


def one_element_graph(name: str, paths: list[str]) -> "nx.DiGraph[str]":
    g: nx.DiGraph[str] = nx.DiGraph()
    g.add_node(name, source_paths=paths)
    return g


def test_folder_pattern_maps_a_file_created_after_the_graph(tmp_path: Path) -> None:
    # the graph describes v1; v2 adds a new file inside the same service folder
    repo = init_repo(tmp_path)
    main = "src/checkoutservice/main.go"
    git_commit(repo, 1, "a@example.com", "checkout service", {main: "package main\n"})
    repo.create_tag("v1")
    new_file = "src/checkoutservice/money/discount.go"
    git_commit(
        repo,
        2,
        "a@example.com",
        "checkout: discounts",
        {main: "package main\n// v2\n", new_file: "package money\nvar rate = 1\n"},
    )
    repo.create_tag("v2")
    repo.close()
    commits = load_commits(
        PyDrillerHistorySource(),
        FakeMiningCache(),
        repo_path=tmp_path,
        from_tag="v1",
        to_tag="v2",
        file_filter=DEFAULT_FILTER,
    )

    by_file = map_to_elements(commits, one_element_graph("checkout", [main]))
    by_folder = map_to_elements(commits, one_element_graph("checkout", ["src/checkoutservice/**"]))

    # main.go +1, discount.go +2: an exact file list misses the new file, the folder does not
    assert by_file.unmapped_files == [new_file]
    assert by_file.unmapped_line_share == pytest.approx(2 / 3)
    assert by_folder.unmapped_files == []
    assert by_folder.commits[0].lines_by_element == {"checkout": 3}
    assert by_folder.unmapped_line_share == 0.0


def test_folder_pattern_matches_whole_folder_names_only() -> None:
    g = one_element_graph("checkout", ["src/checkoutservice/**"])

    history = map_to_elements(
        [
            commit(
                "src/checkoutservice/a/b/c.go",
                "src/checkoutservices/x.go",
                "lib/src/checkoutservice/y.go",
            )
        ],
        g,
    )

    assert history.commits[0].lines_by_element == {"checkout": 3}
    assert history.unmapped_files == ["lib/src/checkoutservice/y.go", "src/checkoutservices/x.go"]


def test_unmapped_line_share_on_the_tiny_repo(tiny: tuple[Path, dict[str, str]]) -> None:
    root, _ = tiny
    commits = load_commits(
        PyDrillerHistorySource(),
        FakeMiningCache(),
        repo_path=root,
        from_tag="v1.0.0",
        to_tag="v1.1.0",
        file_filter=DEFAULT_FILTER,
    )

    history = map_to_elements(commits, graph())

    # kept lines: c2 2 + c1 5 + c3 (util 4 + order 1) + c5 3 = 15, shared util counted once;
    # only Search.py (3 lines) has no owner
    assert (history.total_lines, history.unmapped_lines) == (15, 3)
    assert history.unmapped_line_share == pytest.approx(0.2)


def test_unmapped_share_is_zero_without_changes_and_one_without_paths() -> None:
    assert map_to_elements([], graph()).unmapped_line_share == 0.0
    assert map_to_elements([commit(ORDER)], nx.DiGraph()).unmapped_line_share == 1.0


def test_unmapped_share_is_logged() -> None:
    with capture_logs() as logs:
        map_to_elements([commit(ORDER, "src/other/X.java")], graph())

    (entry,) = [e for e in logs if e["reason"] == "file_unmapped"]
    assert entry["unmapped_line_share"] == 0.5
