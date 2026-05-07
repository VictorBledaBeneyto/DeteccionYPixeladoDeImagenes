import os
import logging
import numpy as np
import cv2

from shared.kafka_client import KafkaProducer, KafkaConsumer
from shared.s3_client import S3Client
from shared import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("o2")

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


def handle(msg: dict):
    guid  = msg["GUID_Solicitud"]
    faces = msg.get("faces", [])
    s3_key = msg["s3_key"]
    logger.info("images.faces_detected | guid=%s faces=%d", guid, len(faces))
    try:
        db.update_solicitud_timestamps(conn, guid, fin_deteccion_caras="NOW()")
        db.update_solicitud_estado(conn, guid, "CARAS_DETECTADAS")

        if not faces:
            db.update_solicitud_timestamps(conn, guid,
                inicio_almacenamiento_solicitud="NOW()",
                fin_almacenamiento_solicitud="NOW()",
                fin_solicitud="NOW()")
            db.update_solicitud_url_terminada(conn, guid, s3_key)
            db.update_solicitud_url_marcos(conn, guid, None)
            db.update_solicitud_estado(conn, guid, "COMPLETADA")
            logger.info("Sin caras → COMPLETADA | guid=%s", guid)
            return

        img_bytes = s3_client.download_bytes(s3_key)
        img_array = np.frombuffer(img_bytes, dtype=np.uint8)
        img       = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        for face in faces:
            id_img = face["id_imagen"]
            bbox   = face["bbox"]
            x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]

            crop = img[y:y+h, x:x+w]
            _, encoded = cv2.imencode(".jpg", crop)
            face_key = f"caras/{guid}/{id_img}.jpg"
            s3_client.upload_bytes(face_key, encoded.tobytes(), content_type="image/jpeg")
            face["url_imagen"] = face_key

            db.insert_imagen(conn, guid, id_img,
                url_imagen=face_key,
                mayor_18=None,
                score=None,
                x=x, y=y, ancho=w, alto=h)

        db.update_solicitud_timestamps(conn, guid, inicio_edad="NOW()")
        producer.publish("images.faces_detected.send", {
            "GUID_Solicitud": guid,
            "s3_key": s3_key,
            "faces": faces,
        }, key=guid)
    except Exception:
        logger.exception("Error en handle | guid=%s", guid)
        db.update_solicitud_estado(conn, guid, "FALLIDA")


if __name__ == "__main__":
    consumer = KafkaConsumer(KAFKA_SERVERS, "o2-group", ["images.faces_detected"])
    logger.info("O2 arrancado.")
    consumer.consume(handle)
