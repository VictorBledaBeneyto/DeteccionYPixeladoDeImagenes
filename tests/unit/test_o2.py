import pytest
from contextlib import contextmanager
from unittest.mock import MagicMock, call, patch
import services.o2.main as o2

def _msg(faces, s3_key="originales/g.jpg", guid="guid-o2"):
    return {"GUID_Solicitud": guid, "s3_key": s3_key, "faces": faces}

def _face(id_imagen=0):
    return {"id_imagen": id_imagen, "bbox": {"x": 5, "y": 5, "w": 20, "h": 20}}

def _setup():
    o2.conn = MagicMock()
    o2.producer = MagicMock()
    o2.s3_client = MagicMock()

@contextmanager
def _mock_image_ops():
    with patch("services.o2.main.cv2") as mock_cv2, \
         patch("services.o2.main.np") as mock_np:
        mock_np.frombuffer.return_value = MagicMock()
        mock_cv2.imdecode.return_value = MagicMock()
        mock_cv2.imencode.return_value = (True, MagicMock())
        yield

class TestO2Handle:
    def test_with_faces_publishes_faces_detected_send(self):
        _setup()
        with patch("services.o2.main.db"), _mock_image_ops():
            o2.handle(_msg([_face()]))

        o2.producer.publish.assert_called_once()
        topic, payload = o2.producer.publish.call_args[0]
        assert topic == "images.faces_detected.send"
        assert payload["GUID_Solicitud"] == "guid-o2"
        assert len(payload["faces"]) == 1

    def test_with_faces_sets_caras_detectadas(self):
        _setup()
        with patch("services.o2.main.db") as mock_db, _mock_image_ops():
            o2.handle(_msg([_face()]))
            mock_db.update_solicitud_estado.assert_any_call(o2.conn, "guid-o2", "CARAS_DETECTADAS")

    def test_with_faces_sets_inicio_edad_timestamp(self):
        _setup()
        with patch("services.o2.main.db") as mock_db, _mock_image_ops():
            o2.handle(_msg([_face()]))
            calls = mock_db.update_solicitud_timestamps.call_args_list
            # One of the calls must set inicio_edad
            assert any("inicio_edad" in str(c) for c in calls)

    def test_no_faces_marks_completada(self):
        _setup()
        with patch("services.o2.main.db") as mock_db:
            o2.handle(_msg([]))
            mock_db.update_solicitud_estado.assert_any_call(o2.conn, "guid-o2", "COMPLETADA")

    def test_no_faces_does_not_publish(self):
        _setup()
        with patch("services.o2.main.db"):
            o2.handle(_msg([]))
        o2.producer.publish.assert_not_called()

    def test_no_faces_sets_fin_solicitud(self):
        _setup()
        with patch("services.o2.main.db") as mock_db:
            o2.handle(_msg([]))
            calls = mock_db.update_solicitud_timestamps.call_args_list
            assert any("fin_solicitud" in str(c) for c in calls)

    def test_db_exception_marks_fallida(self):
        _setup()
        with patch("services.o2.main.db") as mock_db:
            mock_db.update_solicitud_timestamps.side_effect = Exception("DB down")
            o2.handle(_msg([_face()]))
            mock_db.update_solicitud_estado.assert_called_with(o2.conn, "guid-o2", "FALLIDA")

    def test_s3_key_forwarded_when_faces_present(self):
        _setup()
        with patch("services.o2.main.db"), _mock_image_ops():
            o2.handle(_msg([_face()], s3_key="originales/special.jpg"))

        _, payload = o2.producer.publish.call_args[0]
        assert payload["s3_key"] == "originales/special.jpg"
