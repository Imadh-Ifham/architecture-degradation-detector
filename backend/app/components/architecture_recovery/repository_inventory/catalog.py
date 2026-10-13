"""Repository inventory catalog and scan configuration.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Holds every data-driven rule the inventory uses: which directories and
    files to exclude, how filenames map to categories, and how extensions map
    to languages and formats.

    All of it is plain data rather than branch logic, so supporting a new
    language, manifest type or directory convention means adding a table entry
    instead of editing an algorithm. This is what keeps the module free of
    assumptions about any particular language or microservice layout.
"""

from dataclasses import dataclass, field, replace

from app.components.architecture_recovery.repository_inventory.models import (
    Confidence,
    FileCategory,
)


# --------------------------------------------------------------------------- #
# Exclusions
# --------------------------------------------------------------------------- #

# Dependency stores, virtual environments, VCS metadata and build output. These
# hold no first-party architecture information and dominate file counts.
DEFAULT_EXCLUDED_DIRECTORIES: frozenset[str] = frozenset(
    {
        # version control
        ".git", ".hg", ".svn", ".bzr",
        # dependency stores
        "node_modules", "bower_components", "jspm_packages", "vendor",
        "Pods", "Carthage", ".bundle",
        # virtual environments
        ".venv", "venv", "virtualenv", ".tox", "site-packages", "conda-meta",
        # caches
        "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        ".cache", ".parcel-cache", ".turbo", ".gradle", ".terraform",
        # build output
        "dist", "build", "out", "target", "bin", "obj",
        ".next", ".nuxt", ".svelte-kit", ".output",
        # tooling / coverage
        "coverage", ".nyc_output", "htmlcov", "DerivedData",
        # editors
        ".idea", ".vs",
        # ingestion workspace staging area
        ".staging",
    }
)

# Generated lock files: reproducible build artifacts, not architecture evidence.
DEFAULT_EXCLUDED_FILE_NAMES: frozenset[str] = frozenset(
    {
        ".ds_store",
        "thumbs.db",
        "desktop.ini",
        # lock files
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lockb",
        "uv.lock",
        "poetry.lock",
        "pipfile.lock",
        "gemfile.lock",
        "composer.lock",
        "cargo.lock",
        "go.sum",
        "packages.lock.json",
        "project.assets.json",
        "mix.lock",
        "pubspec.lock",
        "flake.lock",
        "gradle.lockfile",
    }
)

# Compiled/generated artifacts, matched on the lowercased file name.
DEFAULT_EXCLUDED_FILE_SUFFIXES: tuple[str, ...] = (
    ".pyc", ".pyo", ".pyd",
    ".class", ".jar", ".war", ".ear",
    ".o", ".obj", ".a", ".lib", ".so", ".dll", ".dylib", ".exe",
    ".min.js", ".min.css", ".map",
    ".log", ".tmp", ".temp", ".swp", ".swo", ".orig", ".rej", ".bak",
)


# --------------------------------------------------------------------------- #
# Filename, path and extension classification rules
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FileNameRule:
    """Maps a lowercased file name (fnmatch pattern) to a category."""

    pattern: str
    category: FileCategory
    language: str | None = None
    format: str | None = None
    confidence: Confidence = Confidence.CONFIRMED


# Ordered: the first matching rule wins, so specific conventions must come
# before generic ones (for example `openapi.yaml` before any generic yaml rule).
FILE_NAME_RULES: tuple[FileNameRule, ...] = (
    # --- deployment manifests --------------------------------------------- #
    FileNameRule("dockerfile*", FileCategory.DEPLOYMENT_MANIFEST, format="dockerfile"),
    FileNameRule("*.dockerfile", FileCategory.DEPLOYMENT_MANIFEST, format="dockerfile"),
    FileNameRule("docker-compose*.y*ml", FileCategory.DEPLOYMENT_MANIFEST, format="yaml"),
    FileNameRule("compose*.y*ml", FileCategory.DEPLOYMENT_MANIFEST, format="yaml"),
    FileNameRule("helmfile*.y*ml", FileCategory.DEPLOYMENT_MANIFEST, format="yaml"),
    FileNameRule("chart.yaml", FileCategory.DEPLOYMENT_MANIFEST, format="yaml"),
    FileNameRule("kustomization*.y*ml", FileCategory.DEPLOYMENT_MANIFEST, format="yaml"),
    FileNameRule("values*.y*ml", FileCategory.DEPLOYMENT_MANIFEST, format="yaml"),
    FileNameRule("skaffold*.y*ml", FileCategory.DEPLOYMENT_MANIFEST, format="yaml"),
    FileNameRule("*deployment*.y*ml", FileCategory.DEPLOYMENT_MANIFEST, format="yaml"),
    FileNameRule("*.service.y*ml", FileCategory.DEPLOYMENT_MANIFEST, format="yaml"),
    FileNameRule("statefulset*.y*ml", FileCategory.DEPLOYMENT_MANIFEST, format="yaml"),
    FileNameRule("daemonset*.y*ml", FileCategory.DEPLOYMENT_MANIFEST, format="yaml"),
    FileNameRule("procfile", FileCategory.DEPLOYMENT_MANIFEST),
    # --- build manifests --------------------------------------------------- #
    FileNameRule("package.json", FileCategory.BUILD_MANIFEST, format="json"),
    FileNameRule("go.mod", FileCategory.BUILD_MANIFEST, language="go"),
    FileNameRule("cargo.toml", FileCategory.BUILD_MANIFEST, language="rust", format="toml"),
    FileNameRule("pyproject.toml", FileCategory.BUILD_MANIFEST, language="python", format="toml"),
    FileNameRule("setup.py", FileCategory.BUILD_MANIFEST, language="python"),
    FileNameRule("setup.cfg", FileCategory.BUILD_MANIFEST, language="python"),
    FileNameRule("pipfile", FileCategory.BUILD_MANIFEST, language="python"),
    FileNameRule("requirements*", FileCategory.BUILD_MANIFEST, language="python", format="text"),
    FileNameRule("pom.xml", FileCategory.BUILD_MANIFEST, language="java", format="xml"),
    FileNameRule("build.gradle*", FileCategory.BUILD_MANIFEST, language="groovy"),
    FileNameRule("settings.gradle*", FileCategory.BUILD_MANIFEST, language="groovy"),
    FileNameRule("gradle.properties", FileCategory.BUILD_MANIFEST, format="properties"),
    FileNameRule("*.csproj", FileCategory.BUILD_MANIFEST, language="csharp", format="xml"),
    FileNameRule("*.fsproj", FileCategory.BUILD_MANIFEST, language="fsharp", format="xml"),
    FileNameRule("*.vbproj", FileCategory.BUILD_MANIFEST, language="vbnet", format="xml"),
    FileNameRule("*.nuspec", FileCategory.BUILD_MANIFEST, format="xml"),
    FileNameRule("build.sbt", FileCategory.BUILD_MANIFEST, language="scala"),
    FileNameRule("mix.exs", FileCategory.BUILD_MANIFEST, language="elixir"),
    FileNameRule("pubspec.yaml", FileCategory.BUILD_MANIFEST, language="dart", format="yaml"),
    FileNameRule("composer.json", FileCategory.BUILD_MANIFEST, language="php", format="json"),
    FileNameRule("gemfile", FileCategory.BUILD_MANIFEST, language="ruby"),
    FileNameRule("deno.json*", FileCategory.BUILD_MANIFEST, language="typescript", format="json"),
    FileNameRule("package.swift", FileCategory.BUILD_MANIFEST, language="swift"),
    FileNameRule("project.clj", FileCategory.BUILD_MANIFEST, language="clojure"),
    FileNameRule("cmakelists.txt", FileCategory.BUILD_MANIFEST),
    FileNameRule("meson.build", FileCategory.BUILD_MANIFEST),
    FileNameRule("makefile", FileCategory.BUILD_MANIFEST),
    FileNameRule("*.mk", FileCategory.BUILD_MANIFEST),
    FileNameRule("*.sln", FileCategory.BUILD_MANIFEST, format="xml"),
    FileNameRule("gradlew*", FileCategory.BUILD_MANIFEST, language="shell"),
    # --- repository and container configuration ---------------------------- #
    FileNameRule(".gitignore", FileCategory.INFRASTRUCTURE_CONFIG),
    FileNameRule(".gitattributes", FileCategory.INFRASTRUCTURE_CONFIG),
    FileNameRule(".dockerignore", FileCategory.INFRASTRUCTURE_CONFIG),
    FileNameRule(".npmignore", FileCategory.INFRASTRUCTURE_CONFIG),
    FileNameRule(".helmignore", FileCategory.INFRASTRUCTURE_CONFIG),
    FileNameRule(".gcloudignore", FileCategory.INFRASTRUCTURE_CONFIG),
    FileNameRule(".editorconfig", FileCategory.INFRASTRUCTURE_CONFIG),
    FileNameRule("codeowners", FileCategory.INFRASTRUCTURE_CONFIG),
    FileNameRule("owners", FileCategory.INFRASTRUCTURE_CONFIG),
    # --- infrastructure configuration -------------------------------------- #
    FileNameRule("*.tf", FileCategory.INFRASTRUCTURE_CONFIG, format="hcl"),
    FileNameRule("*.tfvars", FileCategory.INFRASTRUCTURE_CONFIG, format="hcl"),
    FileNameRule("*.hcl", FileCategory.INFRASTRUCTURE_CONFIG, format="hcl"),
    FileNameRule("*.nomad", FileCategory.INFRASTRUCTURE_CONFIG, format="hcl"),
    FileNameRule("serverless.y*ml", FileCategory.INFRASTRUCTURE_CONFIG, format="yaml"),
    FileNameRule("template.y*ml", FileCategory.INFRASTRUCTURE_CONFIG, format="yaml"),
    FileNameRule("sam.y*ml", FileCategory.INFRASTRUCTURE_CONFIG, format="yaml"),
    FileNameRule("jenkinsfile", FileCategory.INFRASTRUCTURE_CONFIG),
    FileNameRule("vagrantfile", FileCategory.INFRASTRUCTURE_CONFIG),
    FileNameRule("ansible.cfg", FileCategory.INFRASTRUCTURE_CONFIG, format="ini"),
    FileNameRule(".gitlab-ci.y*ml", FileCategory.INFRASTRUCTURE_CONFIG, format="yaml"),
    FileNameRule("azure-pipelines.y*ml", FileCategory.INFRASTRUCTURE_CONFIG, format="yaml"),
    FileNameRule("cloudbuild.y*ml", FileCategory.INFRASTRUCTURE_CONFIG, format="yaml"),
    FileNameRule("buildkite.y*ml", FileCategory.INFRASTRUCTURE_CONFIG, format="yaml"),
    FileNameRule(".travis.y*ml", FileCategory.INFRASTRUCTURE_CONFIG, format="yaml"),
    FileNameRule("*.workflow", FileCategory.INFRASTRUCTURE_CONFIG, format="yaml"),
    FileNameRule("nginx.conf", FileCategory.INFRASTRUCTURE_CONFIG, format="conf"),
    # --- api specifications ------------------------------------------------- #
    FileNameRule("openapi*.json", FileCategory.API_SPECIFICATION, format="json"),
    FileNameRule("openapi*.y*ml", FileCategory.API_SPECIFICATION, format="yaml"),
    FileNameRule("swagger*.json", FileCategory.API_SPECIFICATION, format="json"),
    FileNameRule("swagger*.y*ml", FileCategory.API_SPECIFICATION, format="yaml"),
    FileNameRule("asyncapi*.y*ml", FileCategory.API_SPECIFICATION, format="yaml"),
    FileNameRule("asyncapi*.json", FileCategory.API_SPECIFICATION, format="json"),
    FileNameRule("*.proto", FileCategory.API_SPECIFICATION, language="protobuf"),
    FileNameRule("*.graphql", FileCategory.API_SPECIFICATION, language="graphql"),
    FileNameRule("*.gql", FileCategory.API_SPECIFICATION, language="graphql"),
    FileNameRule("*.wsdl", FileCategory.API_SPECIFICATION, format="wsdl"),
    FileNameRule("*.raml", FileCategory.API_SPECIFICATION, format="raml"),
    # --- database schemas --------------------------------------------------- #
    FileNameRule("*.sql", FileCategory.DATABASE_SCHEMA, language="sql"),
    FileNameRule("*.ddl", FileCategory.DATABASE_SCHEMA, language="sql"),
    FileNameRule("*.psql", FileCategory.DATABASE_SCHEMA, language="sql"),
    # --- tests -------------------------------------------------------------- #
    FileNameRule("test_*.py", FileCategory.TEST, language="python"),
    FileNameRule("*_test.py", FileCategory.TEST, language="python"),
    FileNameRule("conftest.py", FileCategory.TEST, language="python"),
    FileNameRule("*_test.go", FileCategory.TEST, language="go"),
    FileNameRule("*_spec.rb", FileCategory.TEST, language="ruby"),
    FileNameRule("*_test.rb", FileCategory.TEST, language="ruby"),
    FileNameRule("*test.java", FileCategory.TEST, language="java"),
    FileNameRule("*tests.java", FileCategory.TEST, language="java"),
    FileNameRule("*_test.dart", FileCategory.TEST, language="dart"),
    FileNameRule("*.test.ts", FileCategory.TEST, language="typescript"),
    FileNameRule("*.test.tsx", FileCategory.TEST, language="typescript"),
    FileNameRule("*.test.js", FileCategory.TEST, language="javascript"),
    FileNameRule("*.test.jsx", FileCategory.TEST, language="javascript"),
    FileNameRule("*.spec.ts", FileCategory.TEST, language="typescript"),
    FileNameRule("*.spec.tsx", FileCategory.TEST, language="typescript"),
    FileNameRule("*.spec.js", FileCategory.TEST, language="javascript"),
    FileNameRule("*.spec.jsx", FileCategory.TEST, language="javascript"),
    FileNameRule("*.feature", FileCategory.TEST),
    # --- documentation ------------------------------------------------------ #
    FileNameRule("readme*", FileCategory.DOCUMENTATION, format="markdown"),
    FileNameRule("changelog*", FileCategory.DOCUMENTATION, format="markdown"),
    FileNameRule("contributing*", FileCategory.DOCUMENTATION, format="markdown"),
    FileNameRule("code_of_conduct*", FileCategory.DOCUMENTATION, format="markdown"),
    FileNameRule("license*", FileCategory.DOCUMENTATION),
    FileNameRule("notice*", FileCategory.DOCUMENTATION),
    FileNameRule("authors*", FileCategory.DOCUMENTATION),
    FileNameRule("*.md", FileCategory.DOCUMENTATION, format="markdown"),
    FileNameRule("*.mdx", FileCategory.DOCUMENTATION, format="mdx"),
    FileNameRule("*.rst", FileCategory.DOCUMENTATION, format="rst"),
    FileNameRule("*.adoc", FileCategory.DOCUMENTATION, format="asciidoc"),
)

# Directory names that imply a category for everything beneath them. Applied
# only after the filename rules, so `specs/openapi.yaml` is still an API spec.
PATH_SEGMENT_CATEGORIES: dict[str, FileCategory] = {
    "test": FileCategory.TEST,
    "tests": FileCategory.TEST,
    "testing": FileCategory.TEST,
    "__tests__": FileCategory.TEST,
    "testdata": FileCategory.TEST,
    "spec": FileCategory.TEST,
    "specs": FileCategory.TEST,
    "e2e": FileCategory.TEST,
    "docs": FileCategory.DOCUMENTATION,
    "doc": FileCategory.DOCUMENTATION,
    "documentation": FileCategory.DOCUMENTATION,
    "migrations": FileCategory.DATABASE_SCHEMA,
    "migration": FileCategory.DATABASE_SCHEMA,
    "ddl": FileCategory.DATABASE_SCHEMA,
}

# Deployment-style directories. These are weaker evidence than the tables
# above: a `.go` file under `deploy/` is still source code, so this table is
# consulted only for files with no programming language. Entries match as
# substrings of a directory name, so `kubernetes-manifests/`, `k8s/` and
# `deploy/` are all recognised.
INFERRED_PATH_PATTERNS: tuple[tuple[str, FileCategory], ...] = (
    ("deploy", FileCategory.DEPLOYMENT_MANIFEST),
    ("k8s", FileCategory.DEPLOYMENT_MANIFEST),
    ("kubernetes", FileCategory.DEPLOYMENT_MANIFEST),
    ("manifest", FileCategory.DEPLOYMENT_MANIFEST),
    ("helm", FileCategory.DEPLOYMENT_MANIFEST),
    ("chart", FileCategory.DEPLOYMENT_MANIFEST),
)

LANGUAGE_BY_EXTENSION: dict[str, str] = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".java": "java",
    ".kt": "kotlin", ".kts": "kotlin",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
    ".c": "c",
    # `.h` is ambiguous between C and C++ headers; resolved to C by convention.
    ".h": "c",
    ".swift": "swift",
    ".scala": "scala", ".sc": "scala",
    ".dart": "dart",
    ".ex": "elixir", ".exs": "elixir",
    ".erl": "erlang", ".hrl": "erlang",
    ".hs": "haskell", ".lhs": "haskell",
    ".lua": "lua",
    ".r": "r",
    ".jl": "julia",
    ".pl": "perl", ".pm": "perl",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".ksh": "shell", ".fish": "shell",
    ".ps1": "powershell", ".psm1": "powershell", ".psd1": "powershell",
    ".sql": "sql",
    ".graphql": "graphql", ".gql": "graphql",
    ".proto": "protobuf",
    ".vue": "vue",
    ".svelte": "svelte",
    ".html": "html", ".htm": "html",
    ".css": "css",
    ".scss": "scss", ".sass": "scss",
    ".less": "less",
    ".groovy": "groovy", ".gradle": "groovy",
    # `.m` is ambiguous between Objective-C and MATLAB; resolved to Objective-C.
    ".m": "objective-c",
    ".vb": "vbnet",
    ".clj": "clojure", ".cljs": "clojure",
    ".fs": "fsharp", ".fsx": "fsharp",
    ".elm": "elm",
    ".zig": "zig",
    ".nim": "nim",
    ".bzl": "starlark",
    ".asm": "assembly", ".s": "assembly",
}

FORMAT_BY_EXTENSION: dict[str, str] = {
    ".json": "json", ".jsonc": "jsonc", ".json5": "json5",
    ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".ini": "ini", ".cfg": "cfg", ".conf": "conf",
    ".env": "dotenv",
    ".properties": "properties",
    ".csv": "csv", ".tsv": "tsv",
    ".txt": "text",
    ".md": "markdown", ".markdown": "markdown", ".mdx": "mdx",
    ".rst": "rst", ".adoc": "asciidoc",
    ".hcl": "hcl", ".tf": "hcl", ".tfvars": "hcl",
    ".svg": "svg",
    ".wsdl": "wsdl", ".raml": "raml",
    ".diff": "diff", ".patch": "diff",
}

# Formats that are neither code nor a recognised artifact type. These are
# reported as infrastructure configuration at `inferred` confidence, because a
# bare .json/.yaml may equally be application data.
GENERIC_CONFIG_FORMATS: frozenset[str] = frozenset(
    {"json", "jsonc", "json5", "yaml", "toml", "xml", "ini", "conf", "properties", "dotenv"}
)


# --------------------------------------------------------------------------- #
# Scan options
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class InventoryOptions:
    """Controls a single inventory run.

    Exclusions are configurable so a project with an unusual layout can be
    scanned correctly without changing the module.
    """

    excluded_directories: frozenset[str] = DEFAULT_EXCLUDED_DIRECTORIES
    excluded_file_names: frozenset[str] = DEFAULT_EXCLUDED_FILE_NAMES
    excluded_file_suffixes: tuple[str, ...] = DEFAULT_EXCLUDED_FILE_SUFFIXES
    extra_excluded_directories: tuple[str, ...] = field(default_factory=tuple)
    max_files: int = 20_000
    max_file_size_bytes: int = 5_000_000
    # Maximum number of path components a recorded file may have.
    max_depth: int = 32
    # Manifests are the only files whose contents are read; the cap keeps that
    # bounded and avoids loading a generated bundle that looks like a manifest.
    max_manifest_bytes: int = 262_144
    # Only directories at or above this depth are considered for the
    # fallback directory grouping, to avoid proposing a component per folder.
    grouping_depth: int = 2

    def effective_excluded_directories(self) -> frozenset[str]:
        """Return the default exclusions plus any caller-supplied additions."""

        return self.excluded_directories | frozenset(self.extra_excluded_directories)

    def to_dict(self) -> dict:
        """Serialise the options for the inventory's `scan_options` section."""

        return {
            "excluded_directories": sorted(self.effective_excluded_directories()),
            "excluded_file_names": sorted(self.excluded_file_names),
            "excluded_file_suffixes": sorted(self.excluded_file_suffixes),
            "max_files": self.max_files,
            "max_file_size_bytes": self.max_file_size_bytes,
            "max_depth": self.max_depth,
            "max_manifest_bytes": self.max_manifest_bytes,
            "grouping_depth": self.grouping_depth,
        }

    def with_extra_exclusions(self, *directories: str) -> "InventoryOptions":
        """Return a copy excluding the given additional directories."""

        return replace(self, extra_excluded_directories=tuple(sorted(directories)))


DEFAULT_INVENTORY_OPTIONS = InventoryOptions()
