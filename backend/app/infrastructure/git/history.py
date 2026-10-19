# C4 CommitHistorySource over PyDriller: plain commit rows between two release tags.
# Range is git's "from..to" = (from_tag, to_tag]; merge commits are left out; author e-mails
# go through .mailmap (C4-T12, C4-T13).

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
            canonical: dict[str, str] = {}
            rows = []
            for commit_hash in hashes:
                row = _row(git.get_commit(commit_hash))
                email = str(row["author_email"])
                if email not in canonical:
                    canonical[email] = _mailmap(git, email)
                row["author_email"] = canonical[email]
                rows.append(row)
            return rows
        finally:
            git.clear()

    def tag_dates(self, repo_path: str) -> dict[str, str]:
        git = Git(repo_path)
        try:
            return {
                str(tag.name): str(tag.commit.committed_datetime.isoformat())
                for tag in git.repo.tags
            }
        finally:
            git.clear()


def _mailmap(git: Any, email: str) -> str:
    # "git check-mailmap <email>" answers "Name <email>" or "<email>"; unmapped stays as is
    answer = str(git.repo.git.check_mailmap(f"<{email}>"))
    return answer[answer.rfind("<") + 1 : answer.rfind(">")] or email


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
