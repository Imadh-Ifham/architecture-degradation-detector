from fastapi import APIRouter, Depends
from neo4j import Session as Neo4jSession
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.neo4j.database import get_neo4j_session
from app.infrastructure.postgres.database import get_db


router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/postgres")
def postgres_health(db: Session = Depends(get_db)):
    result = db.execute(text("SELECT 1"))
    return {"status": "ok", "database": result.scalar()}


@router.get("/neo4j")
def neo4j_health(
    session: Neo4jSession = Depends(get_neo4j_session),
):
    result = session.run("RETURN 1 AS result")
    record = result.single()

    return {"status": "ok", "database": record["result"]}