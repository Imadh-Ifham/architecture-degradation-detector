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


class HotspotFeatures(BaseModel):
    # the four raw EH features of one event, its elements taken as one unit (CLAUDE.md §5.2)

    model_config = ConfigDict(frozen=True)

    churn_decayed: float = Field(ge=0)
    authors: int = Field(ge=0)
    coupling: int = Field(ge=0)
    bugfix_ratio: float = Field(ge=0, le=1)
    commits: int = Field(ge=0)
    from_release: str
    to_release: str
    first_seen_fallback: bool
    paths_available: bool


class HotspotContext(BaseModel):
    # run-level hotspot settings and state, for the manifest and report

    model_config = ConfigDict(frozen=True)

    active: bool
    inactive_reason: str | None = None
    half_life_days: float | None = None
    decay_rate: float | None = None
    cochange_threshold: int
    max_files_per_commit: int
    unmapped_line_share: float | None = None


class EventFeatures(BaseModel):
    # every criterion's features for one resolved event; AV and PS join in T15-T16

    model_config = ConfigDict(frozen=True)

    event_id: str
    blast_radius: BlastRadiusFeatures
    hotspot: HotspotFeatures | None = None


class FeatureSet(BaseModel):
    # what the features subcomponent hands on: one row per event plus run-level context

    model_config = ConfigDict(frozen=True)

    events: list[EventFeatures]
    hotspot: HotspotContext


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


class MappedFile(BaseModel):
    # one changed file of a commit with the elements that own it (one or more)

    model_config = ConfigDict(frozen=True)

    path: str
    lines: int = Field(ge=0)
    elements: list[str] = Field(min_length=1)


class ElementCommit(BaseModel):
    # a commit seen from the graph: lines changed per element it touched (added + deleted);
    # files = the owned files, so a file shared by two elements can be counted once

    model_config = ConfigDict(frozen=True)

    hash: str
    author_email: str
    committed_at: AwareDatetime
    message: str
    files_changed: int = Field(ge=1)
    lines_by_element: dict[str, int]
    files: list[MappedFile] = Field(default_factory=list)


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
