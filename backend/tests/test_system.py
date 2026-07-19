from fastapi.testclient import TestClient


def test_tauri_production_origin_is_allowed(client: TestClient) -> None:
    response = client.options(
        "/healthz",
        headers={
            "Origin": "http://tauri.localhost",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"
