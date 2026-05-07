import io
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import services.api_upload.main as api_module

client = TestClient(api_module.app)

def _setup():
    api_module.s3_client = MagicMock(upload_bytes=MagicMock(return_value="http://minio/images/orig.jpg"))
    api_module.producer = MagicMock()
    api_module.conn = MagicMock()

class TestPostImages:
    def test_returns_202(self):
        _setup()
        with patch("services.api_upload.main.db"):
            resp = client.post(
                "/images",
                files={"file": ("photo.jpg", b"\xff\xd8\xff", "image/jpeg")},
            )
        assert resp.status_code == 202

    def test_response_contains_guid(self):
        _setup()
        with patch("services.api_upload.main.db"):
            resp = client.post(
                "/images",
                files={"file": ("photo.jpg", b"\xff\xd8\xff", "image/jpeg")},
            )
        data = resp.json()
        assert "GUID_Solicitud" in data
        assert len(data["GUID_Solicitud"]) == 36

    def test_guid_is_unique_per_request(self):
        _setup()
        with patch("services.api_upload.main.db"):
            r1 = client.post("/images", files={"file": ("a.jpg", b"\xff\xd8\xff", "image/jpeg")})
            r2 = client.post("/images", files={"file": ("b.jpg", b"\xff\xd8\xff", "image/jpeg")})
        assert r1.json()["GUID_Solicitud"] != r2.json()["GUID_Solicitud"]

    def test_s3_upload_called(self):
        _setup()
        with patch("services.api_upload.main.db"):
            client.post("/images", files={"file": ("img.jpg", b"data", "image/jpeg")})
        api_module.s3_client.upload_bytes.assert_called_once()

    def test_s3_key_uses_originales_prefix(self):
        _setup()
        with patch("services.api_upload.main.db"):
            client.post("/images", files={"file": ("img.jpg", b"data", "image/jpeg")})
        key = api_module.s3_client.upload_bytes.call_args[0][0]
        assert key.startswith("originales/")

    def test_extension_preserved_in_s3_key(self):
        _setup()
        with patch("services.api_upload.main.db"):
            client.post("/images", files={"file": ("photo.png", b"data", "image/png")})
        key = api_module.s3_client.upload_bytes.call_args[0][0]
        assert key.endswith(".png")

    def test_kafka_event_published(self):
        _setup()
        with patch("services.api_upload.main.db"):
            client.post("/images", files={"file": ("img.jpg", b"data", "image/jpeg")})
        api_module.producer.publish.assert_called_once()
        topic, payload = api_module.producer.publish.call_args[0]
        assert topic == "images.raw.send"
        assert "GUID_Solicitud" in payload
        assert "s3_key" in payload

    def test_db_create_solicitud_called(self):
        _setup()
        with patch("services.api_upload.main.db") as mock_db:
            client.post("/images", files={"file": ("img.jpg", b"data", "image/jpeg")})
        mock_db.create_solicitud.assert_called_once()

    def test_no_file_returns_422(self):
        resp = client.post("/images")
        assert resp.status_code == 422

class TestHealth:
    def test_health_returns_200(self):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_response_body(self):
        resp = client.get("/health")
        assert resp.json() == {"status": "ok"}
