# C4 CommitHistorySource over PyDriller: plain commit rows between two release tags.
# Range is git's "from..to" = (from_tag, to_tag]; merge commits are left out (C4-T12).

from typing import Any

from pydriller import Git


class PyDrillerHistorySource:
    # Reads a local clone; never fetches or changes it.

    def commits(self, repo_path: str, from_tag: str, to_tag: str) -> list[dict[str, object]]:
        git = Git(repo_path)
        try:
            hashes: list[str] = [
                commit.hexsha
                for commit in git.repo.iter_commits(
                    f"{from_tag}..{to_tag}", no_merges=True, reverse=True
                )
            ]
            return [_row(git.get_commit(commit_hash)) for commit_hash in hashes]
        finally:
            git.clear()


def _row(commit: Any) -> dict[str, object]:
    files = [
        {
            # deleted files only have old_path; PyDriller gives OS separators on Windows
            "path": str(change.new_path or change.old_path).replace("\\", "/"),
            "added": int(change.added_lines),
            "deleted": int(change.deleted_lines),
        }
        for change in commit.modified_files
    ]
    return {
        "hash": str(commit.hash),
        "author_email": str(commit.author.email),
        "committed_at": str(commit.committer_date.isoformat()),
        "message": str(commit.msg),
        "files": files,
    }
