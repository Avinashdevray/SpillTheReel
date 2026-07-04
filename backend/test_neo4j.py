import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()
uri = os.getenv("NEO4J_URI")
user = os.getenv("NEO4J_USERNAME")
pwd = os.getenv("NEO4J_PASSWORD")

driver = GraphDatabase.driver(uri, auth=(user, pwd))
try:
    # Try without database name
    with driver.session() as session:
        result = session.run("RETURN 1 AS num")
        print("Default DB success:", result.single()["num"])
except Exception as e:
    print("Default DB error:", e)

try:
    # Try with database="neo4j"
    with driver.session(database="neo4j") as session:
        result = session.run("RETURN 1 AS num")
        print("neo4j DB success:", result.single()["num"])
except Exception as e:
    print("neo4j DB error:", e)
