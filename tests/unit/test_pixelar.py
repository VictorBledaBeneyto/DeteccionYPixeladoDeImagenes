import numpy as np
import cv2
import pytest
from unittest.mock import MagicMock
import services.pixelar.main as pixelar

def _make_image(h=100, w=100, color=(100, 150, 200)):
    return np.full((h, w, 3), color, dtype=np.uint8)

def _encode_jpeg(img: np.ndarray) -> bytes:
    _, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()

def _mock_s3(img: np.ndarray) -> MagicMock:
    m = MagicMock()
    m.download_bytes.return_value = _encode_jpeg(img)
    m.upload_bytes.return_value = "http://minio/images/test.jpg"
    return m

class TestPixelate:
    def test_output_shape_unchanged(self):
        img = _make_image()
        result = pixelar.pixelate(img, 10, 10, 30, 30, factor=5)
        assert result.shape == (100, 100, 3)

    def test_pixels_outside_roi_unchanged(self):
        img = _make_image()
        img[0, 0] = [255, 0, 0]
        pixelar.pixelate(img, 10, 10, 30, 30, factor=5)
        assert list(img[0, 0]) == [255, 0, 0]

    def test_factor_one_leaves_roi_unchanged(self):
        img = _make_image(50, 50, color=(77, 88, 99))
        roi_before = img[5:15, 5:15].copy()
        pixelar.pixelate(img, 5, 5, 10, 10, factor=1)
        assert np.array_equal(img[5:15, 5:15], roi_before)

    def test_pixelated_roi_has_block_structure(self):
        img = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
        pixelar.pixelate(img, 0, 0, 20, 20, factor=20)
        assert img[0, 0].tolist() == img[5, 5].tolist() == img[19, 19].tolist()

class TestDrawFaceAnnotation:
    def _face(self, es_menor: bool, score: float = 0.5):
        return {"bbox": {"x": 10, "y": 10, "w": 30, "h": 30}, "score": score, "es_menor": es_menor}

    def test_modifies_image(self):
        img = _make_image()
        before = img.copy()
        pixelar.draw_face_annotation(img, self._face(False))
        assert not np.array_equal(img, before)

    def test_minor_draws_red_rectangle(self):
        img = _make_image()
        pixelar.draw_face_annotation(img, self._face(True, score=0.9))
        assert np.any(img[:, :, 2] == 255)

    def test_adult_draws_green_rectangle(self):
        img = _make_image()
        pixelar.draw_face_annotation(img, self._face(False, score=0.1))
        assert np.any(img[:, :, 1] == 255)

    def test_missing_score_defaults_to_zero(self):
        img = _make_image()
        face = {"bbox": {"x": 5, "y": 5, "w": 10, "h": 10}}
        pixelar.draw_face_annotation(img, face)

class TestPixelarHandle:
    def _msg(self, faces):
        return {
            "GUID_Solicitud": "test-guid",
            "s3_key": "originales/test-guid.jpg",
            "faces": faces,
        }

    def test_handle_publishes_to_images_processed(self):
        img = _make_image()
        mock_s3 = _mock_s3(img)
        mock_producer = MagicMock()
        pixelar.s3_client = mock_s3
        pixelar.producer = mock_producer

        pixelar.handle(self._msg([
            {"id_imagen": 0, "bbox": {"x": 5, "y": 5, "w": 20, "h": 20}, "score": 0.9, "es_menor": True}
        ]))

        mock_producer.publish.assert_called_once()
        topic, payload = mock_producer.publish.call_args[0]
        assert topic == "images.processed"
        assert payload["GUID_Solicitud"] == "test-guid"
        assert "marcos_key" in payload

    def test_handle_minor_face_url_imagen_preserved(self):
        img = _make_image()
        mock_s3 = _mock_s3(img)
        mock_producer = MagicMock()
        pixelar.s3_client = mock_s3
        pixelar.producer = mock_producer

        pixelar.handle(self._msg([
            {"id_imagen": 0, "bbox": {"x": 5, "y": 5, "w": 20, "h": 20}, "score": 0.9, "es_menor": True}
        ]))

        _, payload = mock_producer.publish.call_args[0]
        assert payload["faces"][0]["url_imagen"] == "caras/test-guid/0.jpg"

    def test_handle_no_faces_publishes_empty_list(self):
        img = _make_image()
        mock_s3 = _mock_s3(img)
        mock_producer = MagicMock()
        pixelar.s3_client = mock_s3
        pixelar.producer = mock_producer

        pixelar.handle(self._msg([]))

        _, payload = mock_producer.publish.call_args[0]
        assert payload["faces"] == []

    def test_handle_multiple_faces(self):
        img = _make_image(200, 200)
        mock_s3 = _mock_s3(img)
        mock_producer = MagicMock()
        pixelar.s3_client = mock_s3
        pixelar.producer = mock_producer

        faces = [
            {"id_imagen": 0, "bbox": {"x": 5, "y": 5, "w": 20, "h": 20}, "score": 0.9, "es_menor": True},
            {"id_imagen": 1, "bbox": {"x": 60, "y": 60, "w": 20, "h": 20}, "score": 0.2, "es_menor": False},
        ]
        pixelar.handle(self._msg(faces))

        _, payload = mock_producer.publish.call_args[0]
        assert len(payload["faces"]) == 2
        keys = [f["url_imagen"] for f in payload["faces"]]
        assert "caras/test-guid/0.jpg" in keys
        assert "caras/test-guid/1.jpg" in keys

    def test_handle_marcos_key_format(self):
        img = _make_image()
        pixelar.s3_client = _mock_s3(img)
        pixelar.producer = MagicMock()

        pixelar.handle(self._msg([]))

        _, payload = mock_producer.publish.call_args[0] if False else pixelar.producer.publish.call_args[0]
        assert payload["marcos_key"] == "marcos/test-guid.jpg"
