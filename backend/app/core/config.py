from pathlib import Path
from tempfile import gettempdir

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "Architecture Degradation Detector"
    app_env: str = "development"
    # Published on the generated API documentation, so a client can tell two
    # deployments apart.
    app_version: str = "0.1.0"

    postgres_host: str
    postgres_port: int = 5434
    postgres_db: str
    postgres_user: str
    postgres_password: str

    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str

    # Local workspace holding ingested (cloned) repositories.
    repositories_root: Path = Path(gettempdir()) / "add-repositories"

    # Where the architecture validation component reads its input from.
    # "snapshot" reads a recorded recovery output, which is what the
    # methodology prescribes while recovery's own extraction is unfinished.
    # "inventory" reads recovery's live inventory document. Never a silent
    # fallback between them: whichever answered is stamped on the run's
    # provenance, so a result always says which input produced it.
    architecture_source: str = "snapshot"
    snapshot_root: Path = BACKEND_ROOT / "data" / "snapshots"
    git_clone_timeout_seconds: int = 300

    # Repository inventory limits. The inventory walks a working tree without
    # reading it; these bound that walk and the few manifests it does open.
    inventory_max_files: int = 20_000
    inventory_max_file_size_bytes: int = 5_000_000
    inventory_max_depth: int = 32
    inventory_max_manifest_bytes: int = 262_144
    inventory_grouping_depth: int = 2
    # Extra directory names to exclude, comma-separated.
    inventory_extra_excluded_directories: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()