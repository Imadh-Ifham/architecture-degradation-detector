"""Run one validation with all three stores wired, and report what landed.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    The route wires one store - the file - because a run on a laptop with no
    databases should report that it wrote one store rather than warn twice
    about two it was never asked to write. This script is the other
    configuration: the file, the relational record and the graph projection,
    all three, which is what the demonstration shows and what fills the
    screens.

    Usage, from `backend/`:

        uv run python -m scripts.demo_c2 v0.10.0
        uv run python -m scripts.demo_c2 v0.10.0 --file-only

    It prints the published path, which stores took the run, and the three
    queries the graph model exists for - so *is it in the database* is
    answered by the output rather than by a claim.

    It is read-only with respect to the subject repository and writes only
    under `artifacts/`, the `c2_` tables and the C2 graph labels.
"""

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.validations import (
    get_ai_client,
    get_architecture_reader,
    get_artifact_reader,
    get_decision_store,
    get_graph_file_store,
    get_release_dates,
)
from app.components.architecture_validation.architect_review import ArchitectReviewService
from app.components.architecture_validation.classification import ClassificationService
from app.components.architecture_validation.decision_knowledge import (
    DecisionKnowledgeService,
)
from app.components.architecture_validation.evidence_retrieval import (
    EvidenceRetrievalService,
)
from app.components.architecture_validation.graph_publishing import (
    GraphPublishingService,
)
from app.components.architecture_validation.independent_verification import (
    IndependentVerificationService,
)
from app.components.architecture_validation.observation_normalization import (
    ObservationNormalizationService,
)
from app.components.architecture_validation.service import ArchitectureValidationService
from app.components.architecture_validation.validation_reasoning import (
    ValidationReasoningService,
)
from app.infrastructure.ai import (
    TASK_PRIMARY_VERDICT,
    TASK_VERIFICATION,
    ai_settings,
    load_prompt,
)
from app.infrastructure.decision_log import JsonlDecisionStore

REPOSITORY = "online-boutique"

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CORPUS = BACKEND_ROOT / "tests" / "fixtures" / "validation" / "subject"
DECISIONS = BACKEND_ROOT / "tests" / "fixtures" / "validation" / "decisions"


class CorpusReader:
    """Reads the committed corpus in place of an ingested checkout.

    The default path needs a clone in the workspace, which is another
    component's step. `--corpus` runs against the recorded subject tree
    instead - the same files the test suite reasons over - so the whole
    component can be demonstrated on a fresh machine with nothing ingested.
    """

    def read_text(self, repository_id, release_id, path):
        return (CORPUS / release_id / path).read_text(encoding="utf-8")

    def list_paths(self, repository_id, release_id, pattern):
        root = CORPUS / release_id
        return sorted(
            str(match.relative_to(root)).replace("\\", "/")
            for match in root.glob(pattern)
            if match.is_file()
        )


def recorder():
    """The relational record, or `None` with the reason printed.

    `None` is *not configured*, which the component reports as one store
    written rather than as a store that failed. A database that is simply not
    running is the normal state on a laptop and not an error here.
    """

    try:
        from app.infrastructure.postgres.database import DATABASE_URL
        from app.infrastructure.postgres.repositories.c2_run_repository import (
            PostgresRunRepository,
        )

        engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 3})
        engine.connect().close()
    except Exception as error:
        print(f"  record     not configured: {_first_line(error)}")
        return None
    return PostgresRunRepository(sessionmaker(bind=engine))


def projection():
    """The graph projection, or `None` with the reason printed."""

    try:
        from app.infrastructure.neo4j.database import driver
        from app.infrastructure.neo4j.validated_graph_projection import (
            Neo4jGraphProjection,
        )

        with driver.session() as session:
            session.run("RETURN 1").single()
    except Exception as error:
        print(f"  projection not configured: {_first_line(error)}")
        return None
    return Neo4jGraphProjection(driver.session)


def pipeline(file_only: bool, corpus: bool) -> ArchitectureValidationService:
    client = get_ai_client()
    artifacts = CorpusReader() if corpus else get_artifact_reader()
    decisions = JsonlDecisionStore(DECISIONS) if corpus else get_decision_store()
    return ArchitectureValidationService(
        architecture_reader=get_architecture_reader(),
        normalization=ObservationNormalizationService(),
        knowledge=DecisionKnowledgeService(artifacts, decisions),
        evidence=EvidenceRetrievalService(artifacts),
        reasoning=ValidationReasoningService(
            client,
            load_prompt("primary_verdict.v1.md"),
            (TASK_PRIMARY_VERDICT,),
            provider=ai_settings.ai_provider,
            allow_arbiter_only=ai_settings.ai_allow_arbiter_only,
        ),
        verification=IndependentVerificationService(
            client,
            load_prompt("critical_reframing.v1.md"),
            TASK_VERIFICATION,
            provider=ai_settings.ai_provider,
        ),
        classification=ClassificationService(),
        review=ArchitectReviewService(),
        publishing=GraphPublishingService(
            get_graph_file_store(),
            None if file_only else recorder(),
            None if file_only else projection(),
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("release", help="the release to validate, e.g. v0.10.0")
    parser.add_argument("--repository", default=REPOSITORY)
    parser.add_argument(
        "--file-only",
        action="store_true",
        help="publish the document and skip both databases",
    )
    parser.add_argument(
        "--corpus",
        action="store_true",
        help="read the committed corpus instead of an ingested checkout",
    )
    arguments = parser.parse_args(argv)

    print(f"stores for {arguments.repository} {arguments.release}:")
    service = pipeline(arguments.file_only, arguments.corpus)

    found = get_release_dates().read(arguments.repository, arguments.release)
    released_at, source = found if found else (None, None)

    run = service.run(
        arguments.repository,
        arguments.release,
        released_at=released_at,
        released_at_source=source,
    )

    stage = next(s for s in run.stages if s.name == "graph_publishing")
    print()
    print(f"run        {run.run_id}  status {run.status}")
    print(f"confidence {run.validation_confidence}  over {len(run.facts)} facts")
    print(f"released   {released_at or 'unknown'}  (source: {source or 'none'})")
    print(f"published  {run.published_ref}")
    print(f"stores     {stage.note or 'nothing written'}")
    for warning in stage.warnings:
        print(f"  warning  {warning}")

    if run.published_ref:
        _report_document(Path(run.published_ref))
    _report_graph(arguments.repository, arguments.release)
    return 0


def _report_document(path: Path) -> None:
    """What a consumer reads, read back the way a consumer reads it."""

    import networkx as nx

    document = json.loads(path.read_text(encoding="utf-8"))
    graph = nx.node_link_graph(document, edges="links")  # the keyword is not optional

    print()
    print("the document, read as the consumer reads it")
    print(f"  schema       {document['graph']['schema_version']}")
    print(f"  nodes/edges  {graph.number_of_nodes()} / {graph.number_of_edges()}")
    print(f"  buckets      {document['graph']['summary']['buckets']}")


def _report_graph(repository_id: str, release_id: str) -> None:
    """The three questions the graph model exists to answer cheaply."""

    try:
        from app.infrastructure.neo4j.database import driver

        with driver.session() as session:
            session.run("RETURN 1").single()
    except Exception as error:
        print()
        print(f"graph store unavailable: {_first_line(error)}")
        return

    print()
    print("the graph store")
    with driver.session() as session:
        totals = session.run(
            """
            MATCH (e:Element {repository_id: $repository_id, release_id: $release_id})
            OPTIONAL MATCH (e)-[d:VALIDATED_DEPENDENCY]->()
            RETURN count(DISTINCT e) AS elements, count(d) AS dependencies
            """,
            repository_id=repository_id,
            release_id=release_id,
        ).single()
        print(f"  elements/dependencies  {totals['elements']} / {totals['dependencies']}")

        chain = session.run(
            """
            MATCH (r:Release {repository_id: $repository_id})
            RETURN r.release_id AS release,
                   r.validation_confidence AS confidence
            ORDER BY r.release_sort_key
            """,
            repository_id=repository_id,
        ).data()
        print("  releases in order      " + ", ".join(
            f"{row['release']}({row['confidence']})" for row in chain
        ))

        worst = session.run(
            """
            MATCH (s:Element {repository_id: $repository_id, release_id: $release_id})
                  -[d:VALIDATED_DEPENDENCY]->(t:Element)
            WHERE d.bucket <> 'confirmed'
            RETURN s.canonical AS source, t.canonical AS target, d.bucket AS bucket,
                   d.confidence AS confidence
            ORDER BY d.confidence
            """,
            repository_id=repository_id,
            release_id=release_id,
        ).data()
        if worst:
            print("  not confirmed")
            for row in worst:
                print(f"    {row['source']} -> {row['target']}  "
                      f"{row['bucket']} {row['confidence']}")
        else:
            print("  not confirmed          none")
    driver.close()


def _first_line(error: Exception) -> str:
    return str(error).splitlines()[0][:90]


if __name__ == "__main__":
    sys.exit(main())
