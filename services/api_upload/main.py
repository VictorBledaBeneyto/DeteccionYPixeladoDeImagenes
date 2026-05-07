import os
import uuid
import logging
from datetime import datetime, timezone

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from shared.kafka_client import KafkaProducer
from shared.s3_client import S3Client
from shared import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("api_upload")

app = FastAPI(title="API Upload - Proyecto Imagenes")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

KAFKA_SERVERS = os.environ["KAFKA_BOOTSTRAP_SERVERS"]
MINIO_ENDPOINT = f"http://{os.environ['MINIO_HOST']}:{os.environ['MINIO_PORT']}"
MINIO_BUCKET   = os.environ["MINIO_BUCKET"]
DB_CONN_PARAMS = dict(
    host=os.environ["POSTGRES_HOST"],
    port=int(os.environ["POSTGRES_PORT"]),
    dbname=os.environ["POSTGRES_DB"],
    user=os.environ["POSTGRES_USER"],
    password=os.environ["POSTGRES_PASSWORD"],
)

producer  = KafkaProducer(KAFKA_SERVERS)
s3_client = S3Client(MINIO_ENDPOINT, os.environ["MINIO_ROOT_USER"], os.environ["MINIO_ROOT_PASSWORD"], MINIO_BUCKET)
conn      = db.get_connection(**DB_CONN_PARAMS)


@app.post("/images", status_code=202)
async def upload_image(file: UploadFile = File(...)):
    guid = str(uuid.uuid4())
    ext  = (file.filename or "image").rsplit(".", 1)[-1].lower()
    s3_key = f"originales/{guid}.{ext}"

    data = await file.read()
    url = s3_client.upload_bytes(s3_key, data, content_type=file.content_type or "image/jpeg")

    db.create_solicitud(conn, guid, url)
    db.update_solicitud_timestamps(conn, guid, inicio_deteccion_caras="NOW()")

    producer.publish("images.raw.send", {
        "GUID_Solicitud": guid,
        "s3_key": s3_key,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, key=guid)

    logger.info("Nueva solicitud | guid=%s s3_key=%s", guid, s3_key)
    return {"GUID_Solicitud": guid}


@app.get("/health")
def health():
    return {"status": "ok"}
