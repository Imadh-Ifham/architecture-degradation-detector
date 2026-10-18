# Data structures returned by the features subcomponent.

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class BlastRadiusFeatures(BaseModel):
    # the four raw BR features of one event; combined into one score in T17

    model_config = ConfigDict(frozen=True)

    fan_in_ratio: float = Field(ge=0, le=1)
    pagerank: float = Field(ge=0)
    betweenness: float = Field(ge=0)
    depth: int = Field(ge=0)
    betweenness_sampled: bool = False


class EventFeatures(BaseModel):
    # every criterion's features for one resolved event; EH, AV and PS join in T13-T16

    model_config = ConfigDict(frozen=True)

    event_id: str
    blast_radius: BlastRadiusFeatures


class FileChange(BaseModel):
    # one file of one commit: posix path, lines added and deleted

    model_config = ConfigDict(frozen=True)

    path: str
    added: int = Field(ge=0)
    deleted: int = Field(ge=0)


class CommitRecord(BaseModel):
    # one non-merge commit as mined from history, files already filtered

    model_config = ConfigDict(frozen=True)

    hash: str
    author_email: str
    committed_at: AwareDatetime
    message: str
    files: list[FileChange]


class ElementCommit(BaseModel):
    # a commit seen from the graph: lines changed per element it touched (added + deleted)

    model_config = ConfigDict(frozen=True)

    hash: str
    author_email: str
    committed_at: AwareDatetime
    message: str
    files_changed: int = Field(ge=1)
    lines_by_element: dict[str, int]


class ElementHistory(BaseModel):
    # commits mapped onto elements, plus the files that hit several elements or none;
    # unmapped_line_share = changed lines no element owns / all changed lines (0 if none)

    model_config = ConfigDict(frozen=True)

    commits: list[ElementCommit] = Field(default_factory=list)
    shared_files: list[str] = Field(default_factory=list)
    unmapped_files: list[str] = Field(default_factory=list)
    total_lines: int = Field(default=0, ge=0)
    unmapped_lines: int = Field(default=0, ge=0)
    unmapped_line_share: float = Field(default=0.0, ge=0, le=1)
