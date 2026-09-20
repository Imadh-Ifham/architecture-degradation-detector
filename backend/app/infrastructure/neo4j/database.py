from collections.abc import Generator

from neo4j import Driver, GraphDatabase

from app.core.config import settings


driver: Driver = GraphDatabase.driver(
    settings.neo4j_uri,
    auth=(
        settings.neo4j_user,
        settings.neo4j_password,
    ),
)

def get_neo4j_session() -> Generator:
    session = driver.session()

    try:
        yield session
    finally:
        session.close()


def close_driver() -> None:
    driver.close()