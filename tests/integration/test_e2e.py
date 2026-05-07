import time
import uuid
import os
import boto3
import psycopg2
import pytest
import requests

pytestmark = pytest.mark.integration

API_URL = os.getenv("TEST_API_URL", "http://localhost:8000")
MINIO_ENDPOINT = os.getenv("TEST_MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "images")

DB_PARAMS = dict(
    host=os.getenv("POSTGRES_HOST", "localhost"),
    port=int(os.getenv("POSTGRES_PORT", "5432")),
    dbname=os.getenv("POSTGRES_DB", "images_db"),
    user=os.getenv("POSTGRES_USER", "postgres"),
    password=os.getenv("POSTGRES_PASSWORD", "postgres"),
)

POLL_INTERVAL = 2
POLL_TIMEOUT  = 60

@pytest.fixture(scope="session")
def db_conn():
    conn = psycopg2.connect(**DB_PARAMS)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def s3():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name="us-east-1",
    )


def _minimal_jpeg() -> bytes:
    import struct
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
        b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),\x01\x01\x01\x01"
        b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4"
        b"\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
        b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xff\xd9"
    )


def _poll_until_completada(db_conn, guid: str, timeout: int = POLL_TIMEOUT) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with db_conn.cursor() as cur:
            cur.execute("SELECT * FROM Solicitud WHERE GUID_Solicitud = %s", (guid,))
            row = cur.fetchone()
        if row and row[0] in ("COMPLETADA", "FALLIDA"):
            return dict(zip([d[0] for d in cur.description], row)) if False else row
        time.sleep(POLL_INTERVAL)
    pytest.fail(f"Solicitud {guid} did not reach COMPLETADA within {timeout}s")


class TestFullPipeline:
    def test_upload_returns_guid(self):
        resp = requests.post(
            f"{API_URL}/images",
            files={"file": ("test.jpg", _minimal_jpeg(), "image/jpeg")},
            timeout=10,
        )
        assert resp.status_code == 202
        assert "GUID_Solicitud" in resp.json()

    def test_pipeline_completes(self, db_conn):
        resp = requests.post(
            f"{API_URL}/images",
            files={"file": ("test.jpg", _minimal_jpeg(), "image/jpeg")},
            timeout=10,
        )
        guid = resp.json()["GUID_Solicitud"]

        deadline = time.time() + POLL_TIMEOUT
        estado = None
        while time.time() < deadline:
            with db_conn.cursor() as cur:
                cur.execute(
                    "SELECT Estado FROM Solicitud WHERE GUID_Solicitud = %s", (guid,)
                )
                row = cur.fetchone()
                if row:
                    estado = row[0]
            if estado in ("COMPLETADA", "FALLIDA"):
                break
            time.sleep(POLL_INTERVAL)

        assert estado == "COMPLETADA", f"Expected COMPLETADA, got {estado}"

    def test_original_image_stored_in_minio(self, db_conn, s3):
        resp = requests.post(
            f"{API_URL}/images",
            files={"file": ("test.jpg", _minimal_jpeg(), "image/jpeg")},
            timeout=10,
        )
        guid = resp.json()["GUID_Solicitud"]

        deadline = time.time() + POLL_TIMEOUT
        while time.time() < deadline:
            with db_conn.cursor() as cur:
                cur.execute("SELECT Estado FROM Solicitud WHERE GUID_Solicitud = %s", (guid,))
                row = cur.fetchone()
            if row and row[0] in ("COMPLETADA", "FALLIDA"):
                break
            time.sleep(POLL_INTERVAL)

        try:
            s3.head_object(Bucket=MINIO_BUCKET, Key=f"originales/{guid}.jpg")
        except Exception:
            pytest.fail(f"Original image not found in MinIO: originales/{guid}.jpg")

    def test_get_solicitud_endpoint(self, db_conn):
        resp = requests.post(
            f"{API_URL}/images",
            files={"file": ("test.jpg", _minimal_jpeg(), "image/jpeg")},
            timeout=10,
        )
        guid = resp.json()["GUID_Solicitud"]

        deadline = time.time() + POLL_TIMEOUT
        while time.time() < deadline:
            with db_conn.cursor() as cur:
                cur.execute("SELECT Estado FROM Solicitud WHERE GUID_Solicitud = %s", (guid,))
                row = cur.fetchone()
            if row and row[0] in ("COMPLETADA", "FALLIDA"):
                break
            time.sleep(POLL_INTERVAL)

        query_resp = requests.get(f"{API_URL}/solicitudes/{guid}", timeout=10)
        assert query_resp.status_code == 200
        data = query_resp.json()
        assert "solicitud" in data
        assert "imagenes" in data

    def test_unknown_guid_returns_404(self):
        resp = requests.get(f"{API_URL}/solicitudes/{uuid.uuid4()}", timeout=10)
        assert resp.status_code == 404

    def test_health_endpoints_reachable(self):
        resp = requests.get(f"{API_URL}/health", timeout=5)
        assert resp.status_code == 200
