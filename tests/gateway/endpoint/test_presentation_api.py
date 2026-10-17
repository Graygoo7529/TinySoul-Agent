from pathlib import Path
import json

from fastapi.testclient import TestClient

from tests.gateway.endpoint.test_endpoint_api import _auth, _engine
from tinysoul.gateway.endpoint.http import create_endpoint_app
from tinysoul.gateway.endpoint.http.schemas.responses import (
    PresentationAssetsResponse,
    PresentationConfigResponse,
)


def test_presentation_works_without_agent_binding_and_preserves_values(
    tmp_path: Path,
) -> None:
    engine, _, _ = _engine(tmp_path)
    engine.unbind()
    with TestClient(create_endpoint_app(engine, engine.settings)) as client:
        path = "/v2/presentation/configs/interface"
        assert client.get(path).status_code == 401
        initial = client.get(path, headers=_auth())
        assert initial.status_code == 200
        assert not initial.json()["exists"]
        response = client.patch(
            path, headers=_auth(), json={"changes": {"theme": "dark"}}
        )
        assert response.status_code == 200
        parsed = PresentationConfigResponse.model_validate_json(
            response.text, strict=True
        )
        assert parsed.exists
        assert parsed.values.theme == "dark"
        assert (tmp_path / "presentation/configs/interface.toml").is_file()
        second = client.patch(
            path, headers=_auth(), json={"changes": {"font_size": 16}}
        )
        assert second.json()["values"]["theme"] == "dark"
        assert client.get(path, headers=_auth()).json()["values"]["font_size"] == 16
        assert (
            client.get("/v2/presentation/configs/unknown", headers=_auth()).status_code
            == 404
        )
        for changes in (
            {"theme": None},
            {"font_size": True},
            {"font_size": 30},
            {"unknown": 1},
            {},
        ):
            invalid = client.patch(path, headers=_auth(), json={"changes": changes})
            assert invalid.status_code == 422
            assert invalid.json()["error"]["code"] == "request.invalid"
        schema = client.get("/openapi.json", headers=_auth()).json()
        assert schema["paths"][path.replace("interface", "{document_id}")]["patch"][
            "responses"
        ]["200"]["content"]["application/json"]["schema"]["$ref"]


def test_presentation_assets_use_authenticated_binary_route(tmp_path: Path) -> None:
    engine, _, _ = _engine(tmp_path)
    image = tmp_path / "presentation/assets/images/test.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    with TestClient(create_endpoint_app(engine, engine.settings)) as client:
        listing = client.get("/v2/presentation/assets", headers=_auth())
        assert listing.status_code == 200
        assets = PresentationAssetsResponse.model_validate_json(
            listing.text, strict=True
        )
        relative = assets.items[0].path
        url = "/v2/presentation/assets/content"
        assert client.get(url, params={"path": relative}).status_code == 401
        response = client.get(url, params={"path": relative}, headers=_auth())
        assert response.content == image.read_bytes()
        assert response.headers["content-type"] == "image/png"
        assert "attachment" in response.headers["content-disposition"]
        invalid = client.get(url, params={"path": "../../secret"}, headers=_auth())
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "presentation.invalid_path"
        assert str(tmp_path) not in json.dumps(invalid.json())
