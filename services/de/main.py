import os
import time
import logging
import numpy as np
import cv2
import torch
import torch.nn as nn
from torchvision import transforms, models
from PIL import Image

from shared.kafka_client import KafkaProducer, KafkaConsumer
from shared.s3_client import S3Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("age_detection")

KAFKA_SERVERS  = os.environ["KAFKA_BOOTSTRAP_SERVERS"]
MINIO_ENDPOINT = f"http://{os.environ['MINIO_HOST']}:{os.environ['MINIO_PORT']}"
MINIO_BUCKET   = os.environ["MINIO_BUCKET"]
MODEL_PATH     = "/app/age_model.pth"

producer  = KafkaProducer(KAFKA_SERVERS)
s3_client = S3Client(MINIO_ENDPOINT, os.environ["MINIO_ROOT_USER"], os.environ["MINIO_ROOT_PASSWORD"], MINIO_BUCKET)

# ── Cargar modelo ──────────────────────────────────────────────────────────────

def load_model(path: str):
    model = models.resnet50(weights=None)
    model.fc = nn.Sequential(
        nn.Linear(model.fc.in_features, 256),
        nn.ReLU(),
        nn.Dropout(0.3),
        nn.Linear(256, 1),
    )
    model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
    model.eval()
    return model

logger.info("Cargando modelo de estimación de edad...")
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model  = load_model(MODEL_PATH).to(device)
logger.info("Modelo cargado en %s", device)

preprocess = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])


def estimate_minor_score(face_bgr: np.ndarray) -> float:
    """P(menor) aplicando sigmoid al logit del clasificador binario."""
    face_rgb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)
    pil_img  = Image.fromarray(face_rgb)
    tensor   = preprocess(pil_img).unsqueeze(0).to(device)
    with torch.no_grad():
        logit = model(tensor).squeeze().item()
    return round(float(torch.sigmoid(torch.tensor(logit)).item()), 4)


# ── Consumer handler ───────────────────────────────────────────────────────────

def handle(msg: dict):
    guid   = msg["GUID_Solicitud"]
    s3_key = msg["s3_key"]
    faces  = msg.get("faces", [])
    t0 = time.perf_counter()

    logger.info("Procesando %d caras | guid=%s", len(faces), guid)

    img_bytes = s3_client.download_bytes(s3_key)
    img_array = np.frombuffer(img_bytes, dtype=np.uint8)
    img       = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

    result_faces = []
    for face in faces:
        bbox = face["bbox"]
        x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
        face_crop = img[y:y+h, x:x+w]

        try:
            score = estimate_minor_score(face_crop)
        except Exception as exc:
            logger.warning("Error estimando edad para cara %d: %s", face["id_imagen"], exc)
            score = 0.0

        es_menor = score > 0.5
        logger.info("Cara %d → score=%.4f es_menor=%s", face["id_imagen"], score, es_menor)

        result_faces.append({**face, "score": score, "es_menor": es_menor})

    elapsed = time.perf_counter() - t0
    logger.info("Age detection completado en %.2fs | guid=%s", elapsed, guid)

    producer.publish("images.age_estimated", {
        "GUID_Solicitud": guid,
        "s3_key": s3_key,
        "faces": result_faces,
    }, key=guid)


if __name__ == "__main__":
    consumer = KafkaConsumer(KAFKA_SERVERS, "age-detection-group", ["images.faces_detected.send"])
    logger.info("Age Detection Service arrancado.")
    consumer.consume(handle)
