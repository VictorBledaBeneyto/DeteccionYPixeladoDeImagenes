import numpy as np
import cv2
import pytest
from unittest.mock import MagicMock, patch
import services.o3.main as o3

def _encode_jpeg(h=100, w=100) -> bytes:
    img = np.full((h, w, 3), 128, dtype=np.uint8)
    _, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()

def _face(id_imagen=0, es_menor=False, score=0.1):
    return {
        "id_imagen": id_imagen,
        "bbox": {"x": 5, "y": 5, "w": 20, "h": 20},
        "score": score,
        "es_menor": es_menor,
    }

def _msg(faces, guid="guid-o3", s3_key="originales/g.jpg"):
    return {"GUID_Solicitud": guid, "s3_key": s3_key, "faces": faces}

def _setup():
    o3.conn = MagicMock()
    o3.producer = MagicMock()
    o3.s3_client = MagicMock(
        download_bytes=MagicMock(return_value=_encode_jpeg()),
        upload_bytes=MagicMock(return_value="http://minio/test.jpg"),
    )

class TestO3Handle:
    def test_with_minor_publishes_age_estimated_send(self):
        _setup()
        with patch("services.o3.main.db") as mock_db:
            o3.handle(_msg([_face(es_menor=True, score=0.9)]))

        o3.producer.publish.assert_called_once()
        topic, payload = o3.producer.publish.call_args[0]
        assert topic == "images.age_estimated.send"
        assert payload["GUID_Solicitud"] == "guid-o3"

    def test_with_minor_sets_edad_calculada(self):
        _setup()
        with patch("services.o3.main.db") as mock_db:
            o3.handle(_msg([_face(es_menor=True)]))
            mock_db.update_solicitud_estado.assert_any_call(o3.conn, "guid-o3", "EDAD_CALCULADA")

    def test_with_minor_sets_inicio_pixelado(self):
        _setup()
        with patch("services.o3.main.db") as mock_db:
            o3.handle(_msg([_face(es_menor=True)]))
            calls = mock_db.update_solicitud_timestamps.call_args_list
            assert any("inicio_pixelado" in str(c) for c in calls)

    def test_no_minors_does_not_publish(self):
        _setup()
        with patch("services.o3.main.db"):
            o3.handle(_msg([_face(es_menor=False)]))
        o3.producer.publish.assert_not_called()

    def test_no_minors_marks_completada(self):
        _setup()
        with patch("services.o3.main.db") as mock_db:
            o3.handle(_msg([_face(es_menor=False)]))
            mock_db.update_solicitud_estado.assert_any_call(o3.conn, "guid-o3", "COMPLETADA")

    def test_no_minors_uploads_full_image_to_definitivas(self):
        _setup()
        with patch("services.o3.main.db"):
            o3.handle(_msg([_face(id_imagen=0, es_menor=False)]))

        uploaded_keys = [c[0][0] for c in o3.s3_client.upload_bytes.call_args_list]
        assert "definitivas/guid-o3.jpg" in uploaded_keys

    def test_no_minors_updates_imagen_age(self):
        _setup()
        with patch("services.o3.main.db") as mock_db:
            o3.handle(_msg([_face(id_imagen=0, es_menor=False, score=0.2)]))
            mock_db.update_imagen_age.assert_called_once()
            args = mock_db.update_imagen_age.call_args[0]
            assert args[1] == "guid-o3"
            assert args[2] == 0

    def test_mixed_faces_with_minor_publishes(self):
        _setup()
        with patch("services.o3.main.db"):
            o3.handle(_msg([_face(0, es_menor=False), _face(1, es_menor=True, score=0.8)]))

        o3.producer.publish.assert_called_once()
        _, payload = o3.producer.publish.call_args[0]
        assert len(payload["faces"]) == 2

    def test_db_exception_marks_fallida(self):
        _setup()
        with patch("services.o3.main.db") as mock_db:
            mock_db.update_solicitud_timestamps.side_effect = Exception("DB error")
            o3.handle(_msg([_face()]))
            mock_db.update_solicitud_estado.assert_called_with(o3.conn, "guid-o3", "FALLIDA")
