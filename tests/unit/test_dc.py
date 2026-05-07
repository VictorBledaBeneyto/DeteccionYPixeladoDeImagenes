import numpy as np
import cv2
import pytest
from unittest.mock import MagicMock

import services.dc.main as dc

def _encode_jpeg(h=100, w=100) -> bytes:
    img = np.full((h, w, 3), 128, dtype=np.uint8)
    _, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()


def _make_mock_box(x1, y1, x2, y2) -> MagicMock:
    box = MagicMock()
    coord = MagicMock()
    coord.tolist.return_value = [x1, y1, x2, y2]
    box.xyxy.__getitem__ = MagicMock(return_value=coord)
    return box

def _configure_model(boxes: list) -> MagicMock:
    mock_results = MagicMock()
    mock_results.__getitem__.return_value.boxes = boxes
    mock_model = MagicMock(return_value=mock_results)
    return mock_model

class TestDCHandle:
    def _base_msg(self):
        return {"GUID_Solicitud": "guid-dc", "s3_key": "originales/guid-dc.jpg"}

    def test_two_faces_published(self):
        dc.s3_client = MagicMock(download_bytes=MagicMock(return_value=_encode_jpeg()))
        dc.producer = MagicMock()
        dc.model = _configure_model([
            _make_mock_box(10, 20, 60, 80),
            _make_mock_box(70, 30, 110, 90),
        ])

        dc.handle(self._base_msg())

        dc.producer.publish.assert_called_once()
        topic, payload = dc.producer.publish.call_args[0]
        assert topic == "images.faces_detected"
        assert payload["GUID_Solicitud"] == "guid-dc"
        assert len(payload["faces"]) == 2

    def test_face_bbox_format(self):
        dc.s3_client = MagicMock(download_bytes=MagicMock(return_value=_encode_jpeg()))
        dc.producer = MagicMock()
        dc.model = _configure_model([_make_mock_box(10, 20, 50, 80)])

        dc.handle(self._base_msg())

        _, payload = dc.producer.publish.call_args[0]
        face = payload["faces"][0]
        assert face["id_imagen"] == 0
        assert face["bbox"] == {"x": 10, "y": 20, "w": 40, "h": 60}

    def test_no_faces_publishes_empty_list(self):
        dc.s3_client = MagicMock(download_bytes=MagicMock(return_value=_encode_jpeg()))
        dc.producer = MagicMock()
        dc.model = _configure_model([])

        dc.handle(self._base_msg())

        _, payload = dc.producer.publish.call_args[0]
        assert payload["faces"] == []

    def test_invalid_image_bytes_publishes_empty_list(self):
        dc.s3_client = MagicMock(download_bytes=MagicMock(return_value=b"not-an-image"))
        dc.producer = MagicMock()
        dc.model = MagicMock()

        dc.handle(self._base_msg())

        dc.producer.publish.assert_called_once()
        _, payload = dc.producer.publish.call_args[0]
        assert payload["faces"] == []

    def test_s3_key_forwarded_in_event(self):
        dc.s3_client = MagicMock(download_bytes=MagicMock(return_value=_encode_jpeg()))
        dc.producer = MagicMock()
        dc.model = _configure_model([])

        dc.handle({"GUID_Solicitud": "g1", "s3_key": "originales/g1.png"})

        _, payload = dc.producer.publish.call_args[0]
        assert payload["s3_key"] == "originales/g1.png"
