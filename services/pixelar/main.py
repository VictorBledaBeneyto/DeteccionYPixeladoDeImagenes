import os
import time
import logging
import numpy as np
import cv2
from shared.kafka_client import KafkaProducer, KafkaConsumer
from shared.s3_client import S3Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("pixelar")

KAFKA_SERVERS  = os.environ["KAFKA_BOOTSTRAP_SERVERS"]
MINIO_ENDPOINT = f"http://{os.environ['MINIO_HOST']}:{os.environ['MINIO_PORT']}"
MINIO_BUCKET   = os.environ["MINIO_BUCKET"]
PIXEL_FACTOR   = int(os.environ.get("PIXELATION_FACTOR", "20"))

producer  = KafkaProducer(KAFKA_SERVERS)
s3_client = S3Client(MINIO_ENDPOINT, os.environ["MINIO_ROOT_USER"], os.environ["MINIO_ROOT_PASSWORD"], MINIO_BUCKET)

def pixelate(img: np.ndarray, x: int, y: int, w: int, h: int, factor: int) -> np.ndarray:
    roi = img[y:y+h, x:x+w]
    small = cv2.resize(roi, (max(1, w // factor), max(1, h // factor)), interpolation=cv2.INTER_LINEAR)
    img[y:y+h, x:x+w] = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    return img

def draw_face_annotation(img: np.ndarray, face: dict) -> None:
    bbox    = face["bbox"]
    x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
    score   = face.get("score", 0.0)
    es_menor = face.get("es_menor", False)

    color = (0, 0, 255) if es_menor else (0, 255, 0)
    cv2.rectangle(img, (x, y), (x + w, y + h), color, 2)

    label = f"{'<18' if es_menor else '>=18'} {score:.2f}"
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(img, (x, y - th - 4), (x + tw + 2, y), color, -1)
    cv2.putText(img, label, (x + 1, y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)

def handle(msg: dict):
    guid   = msg["GUID_Solicitud"]
    s3_key = msg["s3_key"]
    faces  = msg.get("faces", [])
    t0 = time.perf_counter()

    logger.info("Procesando %d caras, guid=%s", len(faces), guid)

    img_bytes = s3_client.download_bytes(s3_key)
    img_array = np.frombuffer(img_bytes, dtype=np.uint8)
    img       = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

    img_marcos = img.copy()
    for face in faces:
        draw_face_annotation(img_marcos, face)

    marcos_key = f"marcos/{guid}.jpg"
    _, marcos_encoded = cv2.imencode(".jpg", img_marcos)
    s3_client.upload_bytes(marcos_key, marcos_encoded.tobytes(), content_type="image/jpeg")

    img_definitivas = img.copy()
    for face in faces:
        if face.get("es_menor"):
            bbox = face["bbox"]
            img_definitivas = pixelate(img_definitivas, bbox["x"], bbox["y"], bbox["w"], bbox["h"], PIXEL_FACTOR)

    definitivas_key = f"definitivas/{guid}.jpg"
    _, def_encoded = cv2.imencode(".jpg", img_definitivas)
    s3_client.upload_bytes(definitivas_key, def_encoded.tobytes(), content_type="image/jpeg")

    result_faces = [{**face, "url_imagen": face.get("url_imagen", f"caras/{guid}/{face['id_imagen']}.jpg")} for face in faces]

    elapsed = time.perf_counter() - t0
    logger.info("Pixelado+enmarcado completado en %.2fs, guid=%s", elapsed, guid)

    producer.publish("images.processed", {
        "GUID_Solicitud": guid,
        "marcos_key": marcos_key,
        "definitivas_key": definitivas_key,
        "faces": result_faces,
    }, key=guid)

if __name__ == "__main__":
    consumer = KafkaConsumer(KAFKA_SERVERS, "pixelar-group", ["images.age_estimated.send"])
    logger.info("Pixelar Service arrancado.")
    consumer.consume(handle)
