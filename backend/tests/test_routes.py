import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client():
    with patch("app.main._configure_cognee"):
        from app.main import app
        # Override the get_current_uid dependency to bypass Firebase verify during tests
        from app.api.routes import get_current_uid
        app.dependency_overrides[get_current_uid] = lambda: "test-user-uid"
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
        
        # Clean up dependency override
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_ingest_empty_url(client):
    response = await client.post("/ingest", json={"url": ""})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_empty_query(client):
    response = await client.get("/chat", params={"q": ""})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_missing_query(client):
    response = await client.get("/chat")
    assert response.status_code == 422


@pytest.mark.asyncio
@patch("app.api.routes.asyncio.create_task")
@patch("app.api.routes.GraphRepository")
async def test_ingest_success(mock_repo, mock_create_task, client):
    response = await client.post(
        "/ingest", json={"url": "https://instagram.com/reel/test"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processing"
    mock_create_task.assert_called_once()
