from app.infrastructure.neo4j.database import driver


def test_neo4j_connection():
    with driver.session() as session:
        result = session.run("RETURN 1 AS result")
        record = result.single()

        assert record["result"] == 1