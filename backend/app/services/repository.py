import os
import time
import logging
from neo4j import GraphDatabase
from neo4j.exceptions import SessionExpired, ServiceUnavailable, DriverError

logger = logging.getLogger("spillthereel.repository")

_STOP_WORDS = {"what", "who", "is", "a", "at", "the", "for", "in",
                "of", "and", "to", "how", "list", "down", "tell",
                "me", "about"}

_NEO4J_MAX_RETRIES = 2

_driver = None

def get_neo4j_driver(force_reconnect=False):
    global _driver
    if force_reconnect and _driver is not None:
        try:
            _driver.close()
        except Exception:
            pass
        _driver = None
    if _driver is None:
        uri = os.getenv("NEO4J_URI")
        user = os.getenv("NEO4J_USERNAME")
        password = os.getenv("NEO4J_PASSWORD")
        if not uri or not user or not password:
            raise RuntimeError("Neo4j environment variables not fully configured.")
        _driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_lifetime=1800,
            connection_acquisition_timeout=30,
        )
    return _driver

def close_neo4j_driver():
    global _driver
    if _driver is not None:
        try:
            _driver.close()
        except Exception:
            pass
        _driver = None

class GraphRepository:
    def __init__(self, driver, uid: str):
        self.driver = driver
        self.uid = uid
        self.db_name = os.environ.get("NEO4J_DATABASE", "neo4j")

    def _get_session(self):
        return self.driver.session(database=self.db_name)

    def save_reel(self, url, transcript, summary, author="", thumbnail=""):
        query = """
        MERGE (u:User {firebase_uid: $uid})
        MERGE (r:Reel {url: $url, owner_uid: $uid})
        SET r.transcript = $transcript, r.summary = $summary,
            r.author = $author, r.thumbnail = $thumbnail,
            r.saved_at = datetime()
        MERGE (u)-[:SAVED]->(r)
        """
        last_exc = None
        for attempt in range(_NEO4J_MAX_RETRIES):
            try:
                with self._get_session() as s:
                    s.run(query, uid=self.uid, url=url, transcript=transcript,
                          summary=summary, author=author, thumbnail=thumbnail)
                return
            except DriverError as exc:
                last_exc = exc
                logger.warning(f"[Neo4J] Driver error, reconnecting ({attempt+1}/{_NEO4J_MAX_RETRIES}): {exc}")
                if attempt < _NEO4J_MAX_RETRIES - 1:
                    self.driver = get_neo4j_driver(force_reconnect=True)
            except (SessionExpired, ServiceUnavailable) as exc:
                last_exc = exc
                logger.warning(f"[Neo4J] Connection issue, retrying ({attempt+1}/{_NEO4J_MAX_RETRIES}): {exc}")
                if attempt < _NEO4J_MAX_RETRIES - 1:
                    time.sleep(1)
        raise last_exc

    def query_reels(self, keyword):
        # Try Neo4j FULLTEXT index first
        raw_words = keyword.lower().replace("?", "").replace(".", "").replace(",", "").split()
        search_words = [w for w in raw_words if w not in _STOP_WORDS and len(w) > 2]

        if search_words:
            lucene_query = " AND ".join(f"{w}~" for w in search_words)
            ft_query = """
            CALL db.index.fulltext.queryNodes('reel_text', $q)
            YIELD node, score
            WHERE node.owner_uid = $uid
            RETURN node.url as url, node.summary as summary,
                   node.transcript as transcript, node.author as author,
                   node.thumbnail as thumbnail, node.saved_at as saved_at,
                   score
            ORDER BY score DESC
            LIMIT 1
            """
            try:
                with self._get_session() as s:
                    result = s.run(ft_query, q=lucene_query, uid=self.uid)
                    records = list(result)
                    if records:
                        r = records[0]
                        d = dict(r)
                        d.pop("score", None)
                        _serialize_saved_at(d)
                        return [d]
            except Exception as exc:
                logger.warning(f"[Repository] FULLTEXT query failed, falling back to scan: {exc}")

        # Fallback: in-memory keyword scoring
        try:
            all_reels = self.get_all_reels()
        except DriverError:
            logger.warning("[Repository] Neo4j driver unavailable for scan fallback.")
            return []
        if not all_reels:
            return []

        if not search_words:
            search_words = [keyword.lower()]

        scored_reels = []
        for r in all_reels:
            text_to_search = (r.get("summary", "") + " " + r.get("transcript", "")).lower()
            score = sum(1 for w in search_words if w in text_to_search)
            if score > 0:
                scored_reels.append((score, r))

        scored_reels.sort(key=lambda x: x[0], reverse=True)
        return [r for score, r in scored_reels[:1]]

    def get_all_reels(self):
        query = """
        MATCH (u:User {firebase_uid: $uid})-[:SAVED]->(r:Reel)
        RETURN r.url as url, r.summary as summary, r.transcript as transcript,
               r.author as author, r.thumbnail as thumbnail, r.saved_at as saved_at
        ORDER BY r.saved_at DESC
        """
        last_exc = None
        for attempt in range(_NEO4J_MAX_RETRIES):
            try:
                with self._get_session() as s:
                    result = s.run(query, uid=self.uid)
                    reels = []
                    for record in result:
                        d = dict(record)
                        _serialize_saved_at(d)
                        reels.append(d)
                    return reels
            except DriverError as exc:
                last_exc = exc
                logger.warning(f"[Neo4J] Driver error in get_all_reels, reconnecting ({attempt+1}): {exc}")
                if attempt < _NEO4J_MAX_RETRIES - 1:
                    self.driver = get_neo4j_driver(force_reconnect=True)
            except (SessionExpired, ServiceUnavailable) as exc:
                last_exc = exc
                logger.warning(f"[Neo4J] Connection issue in get_all_reels, retrying ({attempt+1}): {exc}")
                if attempt < _NEO4J_MAX_RETRIES - 1:
                    time.sleep(1)
        raise last_exc


def _serialize_saved_at(d: dict) -> None:
    sa = d.get("saved_at")
    if sa:
        if hasattr(sa, "iso_format"):
            d["saved_at"] = sa.iso_format()
        elif hasattr(sa, "isoformat"):
            d["saved_at"] = sa.isoformat()
