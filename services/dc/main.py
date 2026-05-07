import os
import time
import logging
import numpy as np
import cv2
from ultralytics import YOLO

from shared.kafka_client import KafkaProducer, KafkaConsumer
from shared.s3_client import S3Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("face_detection")

KAFKA_SERVERS  = os.environ["KAFKA_BOOTSTRAP_SERVERS"]
MINIO_ENDPOINT = f"http://{os.environ['MINIO_HOST']}:{os.environ['MINIO_PORT']}"
MINIO_BUCKET   = os.environ["MINIO_BUCKET"]

producer  = KafkaProducer(KAFKA_SERVERS)
s3_client = S3Client(MINIO_ENDPOINT, os.environ["MINIO_ROOT_USER"], os.environ["MINIO_ROOT_PASSWORD"], MINIO_BUCKET)

logger.info("Cargando modelo YOLOv8-face...")
model = YOLO("/app/yolov8n-face.pt")
logger.info("Modelo listo.")


def handle(msg: dict):
    guid   = msg["GUID_Solicitud"]
    s3_key = msg["s3_key"]
    t0 = time.perf_counter()

    logger.info("Procesando | guid=%s s3_key=%s", guid, s3_key)

    img_bytes  = s3_client.download_bytes(s3_key)
    img_array  = np.frombuffer(img_bytes, dtype=np.uint8)
    img        = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

    if img is None:
        logger.error("No se pudo decodificar la imagen | guid=%s", guid)
        producer.publish("images.faces_detected", {
            "GUID_Solicitud": guid,
            "s3_key": s3_key,
            "faces": [],
        }, key=guid)
        return

    results = model(img, verbose=False)

    faces = []
    for idx, box in enumerate(results[0].boxes):
        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
        faces.append({
            "id_imagen": idx,
            "bbox": {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1},
        })

    elapsed = time.perf_counter() - t0
    logger.info("Detectadas %d caras en %.2fs | guid=%s", len(faces), elapsed, guid)

    producer.publish("images.faces_detected", {
        "GUID_Solicitud": guid,
        "s3_key": s3_key,
        "faces": faces,
    }, key=guid)


if __name__ == "__main__":
    consumer = KafkaConsumer(KAFKA_SERVERS, "face-detection-group", ["images.raw.send"])
    logger.info("Face Detection Service arrancado.")
    consumer.consume(handle)
