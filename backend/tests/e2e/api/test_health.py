import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_ok(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_api_root(client: AsyncClient) -> None:
    response = await client.get("/api")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "trainer-api"
    assert "version" in body
