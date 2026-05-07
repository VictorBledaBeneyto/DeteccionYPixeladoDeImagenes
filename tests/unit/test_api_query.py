import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import services.api_query.main as api_module

client = TestClient(api_module.app)

def _setup():
    api_module.conn = MagicMock()

class TestGetSolicitud:
    def test_returns_200_when_found(self):
        _setup()
        solicitud = {"GUID_Solicitud": "g1", "Estado": "COMPLETADA", "URL_Imagen_Original": "http://x.jpg"}
        with patch("services.api_query.main.db") as mock_db:
            mock_db.get_solicitud.return_value = solicitud
            mock_db.get_imagenes.return_value = []
            resp = client.get("/solicitudes/g1")
        assert resp.status_code == 200

    def test_response_contains_solicitud_and_imagenes(self):
        _setup()
        solicitud = {"GUID_Solicitud": "g1", "Estado": "COMPLETADA"}
        imagenes = [{"Id_Imagen": 0, "Mayor_18": True, "Score": 0.1}]
        with patch("services.api_query.main.db") as mock_db:
            mock_db.get_solicitud.return_value = solicitud
            mock_db.get_imagenes.return_value = imagenes
            resp = client.get("/solicitudes/g1")
        data = resp.json()
        assert "solicitud" in data
        assert "imagenes" in data
        assert len(data["imagenes"]) == 1

    def test_returns_404_when_not_found(self):
        _setup()
        with patch("services.api_query.main.db") as mock_db:
            mock_db.get_solicitud.return_value = None
            resp = client.get("/solicitudes/does-not-exist")
        assert resp.status_code == 404

    def test_404_body_has_detail(self):
        _setup()
        with patch("services.api_query.main.db") as mock_db:
            mock_db.get_solicitud.return_value = None
            resp = client.get("/solicitudes/missing")
        assert "detail" in resp.json()

class TestGetCara:
    def test_returns_200_when_found(self):
        _setup()
        imagen = {"GUID_Solicitud": "g1", "Id_Imagen": 0, "Mayor_18": True, "Score": 0.2}
        with patch("services.api_query.main.db") as mock_db:
            mock_db.get_imagen.return_value = imagen
            resp = client.get("/caras/g1/0")
        assert resp.status_code == 200

    def test_response_body_matches_db_row(self):
        _setup()
        imagen = {"GUID_Solicitud": "g1", "Id_Imagen": 0, "Mayor_18": False, "Score": 0.9}
        with patch("services.api_query.main.db") as mock_db:
            mock_db.get_imagen.return_value = imagen
            resp = client.get("/caras/g1/0")
        assert resp.json()["Score"] == 0.9
        assert resp.json()["Mayor_18"] is False

    def test_returns_404_when_not_found(self):
        _setup()
        with patch("services.api_query.main.db") as mock_db:
            mock_db.get_imagen.return_value = None
            resp = client.get("/caras/g1/99")
        assert resp.status_code == 404

    def test_get_imagen_called_with_correct_params(self):
        _setup()
        imagen = {"GUID_Solicitud": "guid-x", "Id_Imagen": 3}
        with patch("services.api_query.main.db") as mock_db:
            mock_db.get_imagen.return_value = imagen
            client.get("/caras/guid-x/3")
            mock_db.get_imagen.assert_called_once_with(api_module.conn, "guid-x", 3)

class TestHealth:
    def test_health_ok(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
