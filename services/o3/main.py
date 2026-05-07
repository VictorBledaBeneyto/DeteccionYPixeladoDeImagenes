import os
import logging
import numpy as np
import cv2

from shared.kafka_client import KafkaProducer, KafkaConsumer
from shared.s3_client import S3Client
from shared import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("o3")

KAFKA_SERVERS  = os.environ["KAFKA_BOOTSTRAP_SERVERS"]
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


def _draw_face_annotation(img: np.ndarray, face: dict) -> None:
    bbox = face["bbox"]
    x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
    score = face.get("score", 0.0)
    es_menor = face.get("es_menor", False)

    color = (0, 0, 255) if es_menor else (0, 255, 0)
    cv2.rectangle(img, (x, y), (x + w, y + h), color, 2)

    label = f"{'<18' if es_menor else '>=18'} {score:.2f}"
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(img, (x, y - th - 4), (x + tw + 2, y), color, -1)
    cv2.putText(img, label, (x + 1, y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)


def _store_faces_directly(guid: str, s3_key: str, faces: list) -> None:
    img_bytes = s3_client.download_bytes(s3_key)
    img_array = np.frombuffer(img_bytes, dtype=np.uint8)
    img       = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

    img_marcos = img.copy()
    for face in faces:
        _draw_face_annotation(img_marcos, face)

    marcos_key = f"marcos/{guid}.jpg"
    _, marcos_encoded = cv2.imencode(".jpg", img_marcos)
    s3_client.upload_bytes(marcos_key, marcos_encoded.tobytes(), content_type="image/jpeg")

    definitivas_key = f"definitivas/{guid}.jpg"
    _, def_encoded = cv2.imencode(".jpg", img)
    s3_client.upload_bytes(definitivas_key, def_encoded.tobytes(), content_type="image/jpeg")

    for face in faces:
        db.update_imagen_age(conn, guid, face["id_imagen"],
            mayor_18=not face.get("es_menor", False),
            score=face.get("score", 0.0))

    db.update_solicitud_url_terminada(conn, guid, definitivas_key)
    db.update_solicitud_url_marcos(conn, guid, marcos_key)
    db.update_solicitud_timestamps(conn, guid,
        inicio_almacenamiento_solicitud="NOW()",
        fin_almacenamiento_solicitud="NOW()",
        fin_solicitud="NOW()")
    db.update_solicitud_estado(conn, guid, "COMPLETADA")


def handle(msg: dict):
    guid  = msg["GUID_Solicitud"]
    faces = msg.get("faces", [])
    logger.info("images.age_estimated | guid=%s faces=%d", guid, len(faces))
    try:
        db.update_solicitud_timestamps(conn, guid, fin_edad="NOW()")
        db.update_solicitud_estado(conn, guid, "EDAD_CALCULADA")

        menores = [f for f in faces if f.get("es_menor")]

        if menores:
            db.update_solicitud_timestamps(conn, guid, inicio_pixelado="NOW()")
            producer.publish("images.age_estimated.send", {
                "GUID_Solicitud": guid,
                "s3_key": msg["s3_key"],
                "faces": faces,
            }, key=guid)
        else:
            logger.info("Sin menores → almacenando directo | guid=%s", guid)
            _store_faces_directly(guid, msg["s3_key"], faces)
            logger.info("Sin menores → COMPLETADA | guid=%s", guid)
    except Exception:
        logger.exception("Error en handle | guid=%s", guid)
        db.update_solicitud_estado(conn, guid, "FALLIDA")


if __name__ == "__main__":
    consumer = KafkaConsumer(KAFKA_SERVERS, "o3-group", ["images.age_estimated"])
    logger.info("O3 arrancado.")
    consumer.consume(handle)
