from fastapi.testclient import TestClient


def test_web_origin_is_allowed(client: TestClient) -> None:
    response = client.options(
        "/healthz",
        headers={
            "Origin": "http://127.0.0.1:1420",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:1420"
