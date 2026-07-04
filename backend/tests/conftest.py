import os
import pytest
from pathlib import Path

TEST_COOKIES_FILE = Path(__file__).resolve().parent / "test_cookies.txt"


@pytest.fixture(autouse=True)
def set_env_vars():
    os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
    os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
    os.environ.setdefault("NEO4J_URI", "neo4j+s://test.databases.neo4j.io")
    os.environ.setdefault("NEO4J_USERNAME", "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "test-password")
    os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
    os.environ.setdefault("COGNEE_DATA_PATH", str(Path(__file__).resolve().parent / ".cognee_data"))


@pytest.fixture
def mock_video_path(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video content")
    return str(video)


@pytest.fixture
def mock_cookies_file(tmp_path):
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    return str(cookies)
