import numpy as np
import cv2
import pytest
from unittest.mock import MagicMock, patch
import services.de.main as de

def _encode_jpeg(h=100, w=100) -> bytes:
    img = np.full((h, w, 3), 128, dtype=np.uint8)
    _, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()

def _face(id_imagen, x=5, y=5, w=20, h=20):
    return {"id_imagen": id_imagen, "bbox": {"x": x, "y": y, "w": w, "h": h}}

class TestDEHandle:
    def _setup(self):
        de.s3_client = MagicMock(download_bytes=MagicMock(return_value=_encode_jpeg()))
        de.producer = MagicMock()

    def test_score_above_threshold_marks_minor(self):
        self._setup()
        with patch.object(de, "estimate_minor_score", return_value=0.9):
            de.handle({
                "GUID_Solicitud": "g1",
                "s3_key": "originales/g1.jpg",
                "faces": [_face(0)],
            })

        _, payload = de.producer.publish.call_args[0]
        assert payload["faces"][0]["es_menor"] is True
        assert payload["faces"][0]["score"] == 0.9

    def test_score_below_threshold_marks_adult(self):
        self._setup()
        with patch.object(de, "estimate_minor_score", return_value=0.3):
            de.handle({
                "GUID_Solicitud": "g2",
                "s3_key": "originales/g2.jpg",
                "faces": [_face(0)],
            })

        _, payload = de.producer.publish.call_args[0]
        assert payload["faces"][0]["es_menor"] is False
        assert payload["faces"][0]["score"] == 0.3

    def test_score_exactly_threshold_is_adult(self):
        self._setup()
        with patch.object(de, "estimate_minor_score", return_value=0.5):
            de.handle({
                "GUID_Solicitud": "g3",
                "s3_key": "originales/g3.jpg",
                "faces": [_face(0)],
            })

        _, payload = de.producer.publish.call_args[0]
        assert payload["faces"][0]["es_menor"] is False

    def test_error_in_estimate_defaults_score_to_zero(self):
        self._setup()
        with patch.object(de, "estimate_minor_score", side_effect=ValueError("bad crop")):
            de.handle({
                "GUID_Solicitud": "g4",
                "s3_key": "originales/g4.jpg",
                "faces": [_face(0)],
            })

        _, payload = de.producer.publish.call_args[0]
        assert payload["faces"][0]["score"] == 0.0
        assert payload["faces"][0]["es_menor"] is False

    def test_no_faces_publishes_empty_list(self):
        self._setup()
        with patch.object(de, "estimate_minor_score"):
            de.handle({"GUID_Solicitud": "g5", "s3_key": "originales/g5.jpg", "faces": []})

        _, payload = de.producer.publish.call_args[0]
        assert payload["faces"] == []

    def test_multiple_faces_all_processed(self):
        self._setup()
        scores = [0.9, 0.1, 0.7]
        with patch.object(de, "estimate_minor_score", side_effect=scores):
            de.handle({
                "GUID_Solicitud": "g6",
                "s3_key": "originales/g6.jpg",
                "faces": [_face(0), _face(1, x=50), _face(2, x=100)],
            })

        _, payload = de.producer.publish.call_args[0]
        assert len(payload["faces"]) == 3
        assert [f["es_menor"] for f in payload["faces"]] == [True, False, True]

    def test_publishes_to_images_age_estimated(self):
        self._setup()
        with patch.object(de, "estimate_minor_score", return_value=0.0):
            de.handle({"GUID_Solicitud": "g7", "s3_key": "originales/g7.jpg", "faces": []})

        topic, _ = de.producer.publish.call_args[0]
        assert topic == "images.age_estimated"

    def test_guid_forwarded_in_event(self):
        self._setup()
        with patch.object(de, "estimate_minor_score", return_value=0.0):
            de.handle({"GUID_Solicitud": "unique-guid", "s3_key": "x.jpg", "faces": []})

        _, payload = de.producer.publish.call_args[0]
        assert payload["GUID_Solicitud"] == "unique-guid"
