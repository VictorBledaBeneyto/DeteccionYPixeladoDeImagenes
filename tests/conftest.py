import os
import sys
from unittest.mock import MagicMock

_ENV = {
    "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
    "MINIO_HOST": "localhost",
    "MINIO_PORT": "9000",
    "MINIO_BUCKET": "images",
    "MINIO_ROOT_USER": "minioadmin",
    "MINIO_ROOT_PASSWORD": "minioadmin",
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "images_db",
    "POSTGRES_USER": "postgres",
    "POSTGRES_PASSWORD": "postgres",
}
for _k, _v in _ENV.items():
    os.environ.setdefault(_k, _v)

sys.modules.setdefault("confluent_kafka", MagicMock())

sys.modules.setdefault("ultralytics", MagicMock())

_torch = MagicMock()
_torch.no_grad.return_value.__enter__ = MagicMock(return_value=None)
_torch.no_grad.return_value.__exit__ = MagicMock(return_value=False)
sys.modules.setdefault("torch", _torch)
sys.modules.setdefault("torch.nn", MagicMock())
sys.modules.setdefault("torchvision", MagicMock())
sys.modules.setdefault("torchvision.transforms", MagicMock())
sys.modules.setdefault("torchvision.models", MagicMock())
sys.modules.setdefault("PIL", MagicMock())
sys.modules.setdefault("PIL.Image", MagicMock())

_psycopg2 = MagicMock()
_psycopg2.connect = MagicMock(return_value=MagicMock())
_psycopg2.extras = MagicMock()
_psycopg2.extras.RealDictCursor = MagicMock()
sys.modules.setdefault("psycopg2", _psycopg2)
sys.modules.setdefault("psycopg2.extras", _psycopg2.extras)
sys.modules.setdefault("psycopg2.sql", MagicMock())
