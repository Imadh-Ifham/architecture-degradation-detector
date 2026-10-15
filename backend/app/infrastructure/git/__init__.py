"""Git adapter package.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Exposes the low-level git command-line adapter used by the research
    components to read local and remote repositories.
"""

from app.infrastructure.git.client import GitClient, GitCommandError

__all__ = ["GitClient", "GitCommandError"]
