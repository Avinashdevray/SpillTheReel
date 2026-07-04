import os
import asyncio
from dotenv import load_dotenv
import cognee

load_dotenv()
neo4j_uri = os.getenv("NEO4J_URI")
neo4j_user = os.getenv("NEO4J_USERNAME")
neo4j_pass = os.getenv("NEO4J_PASSWORD")

cognee.config.set_graph_database_provider("neo4j")
cognee.config.set_graph_db_config({
    "graph_database_url": neo4j_uri,
    "graph_database_username": neo4j_user,
    "graph_database_password": neo4j_pass,
    "graph_database_database": "" # or None
})
async def test():
    from cognee.infrastructure.databases.graph.get_graph_engine import get_graph_engine
    engine = get_graph_engine()
    await engine.get_edges(None)
    print("Graph engine OK")
asyncio.run(test())
