"""Recording one validation run.

Author: Aman Mohamed M.A
Date: 2026-10-19
Description:
    The `ValidationRunRecorder` the component writes through.

    Idempotent per run: a re-recorded run deletes its own rows first. The run
    id is content-free and a second recording of one run means the first was
    interrupted, so replacing it is the only reading that leaves the table
    describing what happened once.

    Every row here is derivable from the published document, which is what
    makes a failed record recoverable rather than lost - the component treats
    a store that refused as a warning for exactly that reason.
"""

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from app.domain.validated_architecture import ValidatedArchitectureGraph
from app.infrastructure.postgres.models.c2_validation_run import (
    C2_TABLES,
    c2_classified_fact,
    c2_element,
    c2_objection,
    c2_primary_verdict,
    c2_stage_record,
    c2_validation_run,
    c2_verification,
)


class PostgresRunRepository:
    """Writes a completed run's rows in one transaction."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def record(self, run, document: ValidatedArchitectureGraph) -> None:
        """Store the run, its stages, its facts and both model outputs.

        One transaction. A half-written run is worse than an absent one: the
        correlated-failure query joins the two verdict tables, and a run whose
        verifications landed and whose verdicts did not would answer it with a
        number that looks real.
        """

        with self._sessions.begin() as session:
            self._forget(session, run.run_id)
            session.execute(c2_validation_run.insert(), _run_row(run, document))

            stages = [_stage_row(run.run_id, stage) for stage in run.stages]
            if stages:
                session.execute(c2_stage_record.insert(), stages)

            elements = [_element_row(run.run_id, node) for node in document.nodes]
            if elements:
                session.execute(c2_element.insert(), elements)

            facts = [_fact_row(run.run_id, fact) for fact in run.facts]
            if facts:
                session.execute(c2_classified_fact.insert(), facts)

            verdicts = [
                _verdict_row(run.run_id, fact.verdict)
                for fact in run.facts
                if fact.verdict is not None
            ]
            if verdicts:
                session.execute(c2_primary_verdict.insert(), verdicts)

            checks = [
                fact.verification for fact in run.facts if fact.verification is not None
            ]
            if checks:
                session.execute(
                    c2_verification.insert(),
                    [_verification_row(run.run_id, check) for check in checks],
                )

            objections = [
                _objection_row(run.run_id, check.fact_id, ordinal, objection)
                for check in checks
                for ordinal, objection in enumerate(check.objections)
            ]
            if objections:
                session.execute(c2_objection.insert(), objections)

    def _forget(self, session: Session, run_id: str) -> None:
        """Remove this run's previous rows, children first."""

        for table in reversed(C2_TABLES):
            session.execute(delete(table).where(table.c.run_id == run_id))


def _run_row(run, document: ValidatedArchitectureGraph) -> dict:
    return {
        "run_id": run.run_id,
        "repository_id": run.repository_id,
        "release_id": run.release_id,
        # Stored as text rather than an integer array so one column orders
        # releases without the reader knowing how many segments a key has.
        "release_sort_key": ".".join(f"{part:05d}" for part in document.release_order_key),
        "released_at": run.released_at,
        "released_at_source": run.released_at_source,
        "c1_model_ref": document.c1_model_ref,
        "schema_version": document.to_node_link()["graph"]["schema_version"],
        "status": run.status,
        "generated_at": run.generated_at,
        "decision_mode": run.decision_mode,
        "style_resolved": run.style_resolved,
        "style_source": run.style_source,
        "verification_mode": run.verification_mode,
        "verification_arm": run.verification_arm,
        "model_calls": run.model_calls,
        "validation_confidence": run.validation_confidence,
        "reasoner_model": run.reasoner_model,
        "verifier_model": run.verifier_model,
        "prompt_versions": list(run.prompt_versions),
        "published_ref": run.published_ref,
    }


def _stage_row(run_id: str, stage) -> dict:
    return {
        "run_id": run_id,
        "name": stage.name,
        "status": str(stage.status),
        "counts": dict(stage.counts),
        "duration_ms": stage.duration_ms,
        "note": stage.note,
        "warnings": list(stage.warnings),
    }


def _element_row(run_id: str, node) -> dict:
    return {
        "run_id": run_id,
        "element_id": node.id,
        "canonical": node.canonical or node.name,
        "name": node.name,
        "kind": str(node.kind),
        "size": node.size,
        "size_unit": node.size_unit,
        "confirmed": node.rollup.confirmed,
        "contradicted": node.rollup.contradicted,
        "uncovered": node.rollup.uncovered,
        "needs_review": node.rollup.needs_review,
    }


def _fact_row(run_id: str, fact) -> dict:
    return {
        "run_id": run_id,
        "fact_id": fact.fact_id,
        "source_element_id": fact.source_element_id,
        "target_element_id": fact.target_element_id,
        "relationship": str(fact.relationship),
        "bucket": str(fact.bucket),
        "confidence": fact.confidence,
        "score_trace": fact.score_trace.to_dict(),
        "route": str(fact.route),
        "governing_decision": fact.governing_decision,
        "source_tier": str(fact.source_tier) if fact.source_tier else None,
        "evidence_refs": list(fact.evidence_refs),
        "model_calls": fact.model_calls,
        "produced_by": fact.produced_by or None,
        "verification_outcome": (
            str(fact.verification_outcome) if fact.verification_outcome else None
        ),
        "arbiter_agreement": (
            str(fact.arbiter_agreement) if fact.arbiter_agreement else None
        ),
        "attributes": dict(fact.attributes),
    }


def _verdict_row(run_id: str, verdict) -> dict:
    return {
        "run_id": run_id,
        "fact_id": verdict.fact_id,
        "verdict": str(verdict.verdict),
        "reasoning": verdict.reasoning,
        "cited_evidence_refs": list(verdict.cited_evidence_refs),
        "model_id": verdict.model_id,
        "prompt_version": verdict.prompt_version,
        "evidence_hash": verdict.evidence_hash,
        "cached": verdict.cached,
        "retried": verdict.retried,
        "provider": verdict.provider or None,
        "schema_mode": verdict.schema_mode or None,
        "produced_by": str(verdict.produced_by),
        # The row of the table the arbiter used, kept beside its answer. A
        # mechanical verdict looks authoritative and is only as good as the
        # rule extraction above it.
        "arbiter_verdict": (
            str(verdict.arbiter.verdict)
            if verdict.arbiter is not None and verdict.arbiter.verdict is not None
            else None
        ),
        "arbiter_basis": verdict.arbiter.basis if verdict.arbiter is not None else None,
        "arbiter_agreement": (
            str(verdict.arbiter_agreement) if verdict.arbiter_agreement else None
        ),
        # Kept even when the retry succeeded. An incoherent answer and an
        # invented reference have different fixes, and the rate of each is a
        # result about the model rather than an incident in a log.
        "guard_failures": [str(failure) for failure in verdict.guard_failures],
        "ladder_rung": verdict.ladder_rung,
    }


def _verification_row(run_id: str, check) -> dict:
    return {
        "run_id": run_id,
        "fact_id": check.fact_id,
        "outcome": str(check.outcome),
        "mechanism": check.mechanism,
        "reasoning": check.reasoning,
        "model_id": check.model_id,
        "prompt_version": check.prompt_version,
        "evidence_hash": check.evidence_hash,
        "challenged_model_id": check.challenged_model_id or None,
        "cached": check.cached,
        "retried": check.retried,
        "provider": check.provider or None,
        "schema_mode": check.schema_mode or None,
        "guard_failures": [str(failure) for failure in check.guard_failures],
    }


def _objection_row(run_id: str, fact_id: str, ordinal: int, objection) -> dict:
    return {
        "run_id": run_id,
        "fact_id": fact_id,
        "ordinal": ordinal,
        "kind": str(objection.kind),
        "ref": objection.ref,
        "statement": objection.statement,
    }
