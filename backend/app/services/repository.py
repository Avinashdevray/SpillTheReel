import os
import logging
from neo4j import GraphDatabase

logger = logging.getLogger("spillthereel.repository")

_driver = None

def get_neo4j_driver():
    global _driver
    if _driver is None:
        uri = os.getenv("NEO4J_URI")
        user = os.getenv("NEO4J_USERNAME")
        password = os.getenv("NEO4J_PASSWORD")
        if not uri or not user or not password:
            raise RuntimeError("Neo4j environment variables not fully configured.")
        _driver = GraphDatabase.driver(uri, auth=(user, password))
    return _driver

def close_neo4j_driver():
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None

class GraphRepository:
    def __init__(self, driver, uid: str):
        self.driver = driver
        self.uid = uid  # bound at construction, from Firebase JWT
        self.db_name = os.environ.get("NEO4J_DATABASE", "neo4j")

    def _get_session(self):
        # Allow multi-db mode if env var is set, default to standard DB name
        if os.environ.get("MULTI_DB_MODE") == "true":
            return self.driver.session(database=f"tenant_{self.uid}")
        return self.driver.session(database=self.db_name)

    def save_reel(self, url, transcript, summary, author="", thumbnail=""):
        query = """
        MERGE (u:User {firebase_uid: $uid})
        MERGE (r:Reel {url: $url, owner_uid: $uid})
        SET r.transcript = $transcript, r.summary = $summary, r.author = $author, r.thumbnail = $thumbnail, r.saved_at = datetime()
        MERGE (u)-[:SAVED]->(r)
        """
        with self._get_session() as s:
            s.run(query, uid=self.uid, url=url, transcript=transcript, summary=summary, author=author, thumbnail=thumbnail)

    def query_reels(self, keyword):
        # Instead of strict Cypher CONTAINS (which fails on natural language),
        # we fetch all reels and do a keyword overlap score in Python.
        all_reels = self.get_all_reels()
        if not all_reels:
            return []

        # Simple stop words to ignore
        stop_words = {"what", "who", "is", "a", "at", "is", "the", "for", "in", "of", "and", "to", "how", "list", "down", "tell", "me", "about"}
        
        # Extract meaningful keywords from the query
        raw_words = keyword.lower().replace("?", "").replace(".", "").replace(",", "").split()
        search_words = [w for w in raw_words if w not in stop_words and len(w) > 2]
        
        if not search_words:
            # If query was just stop words, fallback to matching the raw string
            search_words = [keyword.lower()]

        scored_reels = []
        for r in all_reels:
            text_to_search = (r.get("summary", "") + " " + r.get("transcript", "")).lower()
            score = 0
            for w in search_words:
                if w in text_to_search:
                    score += 1
            if score > 0:
                scored_reels.append((score, r))
                
        # Sort by highest score first, return top 5
        scored_reels.sort(key=lambda x: x[0], reverse=True)
        return [r for score, r in scored_reels[:5]]

    def get_all_reels(self):
        query = """
        MATCH (u:User {firebase_uid: $uid})-[:SAVED]->(r:Reel)
        RETURN r.url as url, r.summary as summary, r.transcript as transcript, r.author as author, r.thumbnail as thumbnail, r.saved_at as saved_at
        ORDER BY r.saved_at DESC
        """
        with self._get_session() as s:
            result = s.run(query, uid=self.uid)
            reels = []
            for record in result:
                d = dict(record)
                # Convert neo4j.time.DateTime to string for JSON serialization
                if 'saved_at' in d and hasattr(d['saved_at'], 'iso_format'):
                    d['saved_at'] = d['saved_at'].iso_format()
                elif 'saved_at' in d and hasattr(d['saved_at'], 'isoformat'):
                    d['saved_at'] = d['saved_at'].isoformat()
                reels.append(d)
            return reels
