import os
import logging

from shared.kafka_client import KafkaConsumer
from shared import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("o4")

KAFKA_SERVERS = os.environ["KAFKA_BOOTSTRAP_SERVERS"]
DB_CONN_PARAMS = dict(
    host=os.environ["POSTGRES_HOST"],
    port=int(os.environ["POSTGRES_PORT"]),
    dbname=os.environ["POSTGRES_DB"],
    user=os.environ["POSTGRES_USER"],
    password=os.environ["POSTGRES_PASSWORD"],
)

conn = db.get_connection(**DB_CONN_PARAMS)


def handle(msg: dict):
    guid            = msg["GUID_Solicitud"]
    faces           = msg.get("faces", [])
    marcos_key      = msg.get("marcos_key")
    definitivas_key = msg.get("definitivas_key")
    logger.info("images.processed | guid=%s faces=%d", guid, len(faces))
    try:
        for face in faces:
            db.update_imagen_age(conn, guid, face["id_imagen"],
                mayor_18=not face.get("es_menor", False),
                score=face.get("score", 0.0))

        db.update_solicitud_url_terminada(conn, guid, definitivas_key)
        db.update_solicitud_url_marcos(conn, guid, marcos_key)
        db.update_solicitud_timestamps(conn, guid,
            fin_pixelado="NOW()",
            inicio_almacenamiento_solicitud="NOW()",
            fin_almacenamiento_solicitud="NOW()",
            fin_solicitud="NOW()")
        db.update_solicitud_estado(conn, guid, "COMPLETADA")
        logger.info("Pipeline COMPLETADA | guid=%s", guid)
    except Exception:
        logger.exception("Error en handle | guid=%s", guid)
        db.update_solicitud_estado(conn, guid, "FALLIDA")


if __name__ == "__main__":
    consumer = KafkaConsumer(KAFKA_SERVERS, "o4-group", ["images.processed"])
    logger.info("O4 arrancado.")
    consumer.consume(handle)
