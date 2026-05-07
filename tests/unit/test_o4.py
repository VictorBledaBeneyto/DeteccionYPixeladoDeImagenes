import pytest
from unittest.mock import MagicMock, patch
import services.o4.main as o4

def _face(id_imagen=0, es_menor=False, score=0.1, url="definitivas/g/0.jpg"):
    return {
        "id_imagen": id_imagen,
        "bbox": {"x": 5, "y": 5, "w": 20, "h": 20},
        "score": score,
        "es_menor": es_menor,
        "url_imagen": url,
    }

def _msg(faces, guid="guid-o4", marcos_key="marcos/guid-o4.jpg",
         definitivas_key="definitivas/guid-o4.jpg"):
    return {
        "GUID_Solicitud": guid,
        "faces": faces,
        "marcos_key": marcos_key,
        "definitivas_key": definitivas_key,
    }

def _setup():
    o4.conn = MagicMock()

class TestO4Handle:
    def test_updates_one_row_per_face(self):
        _setup()
        with patch("services.o4.main.db") as mock_db:
            o4.handle(_msg([_face(0), _face(1, url="definitivas/g/1.jpg")]))
            assert mock_db.update_imagen_age.call_count == 2

    def test_update_imagen_age_correct_args(self):
        _setup()
        with patch("services.o4.main.db") as mock_db:
            o4.handle(_msg([_face(0, es_menor=True, score=0.9)]))
            c = mock_db.update_imagen_age.call_args
            pos, kw = c.args, c.kwargs
            assert pos[1] == "guid-o4"
            assert pos[2] == 0
            assert kw["mayor_18"] is False
            assert kw["score"] == 0.9

    def test_adult_face_mayor_18_true(self):
        _setup()
        with patch("services.o4.main.db") as mock_db:
            o4.handle(_msg([_face(0, es_menor=False)]))
            kw = mock_db.update_imagen_age.call_args.kwargs
            assert kw["mayor_18"] is True

    def test_marks_completada(self):
        _setup()
        with patch("services.o4.main.db") as mock_db:
            o4.handle(_msg([_face()]))
            mock_db.update_solicitud_estado.assert_called_once_with(o4.conn, "guid-o4", "COMPLETADA")

    def test_sets_url_terminada_to_definitivas_and_marcos_to_marcos(self):
        _setup()
        with patch("services.o4.main.db") as mock_db:
            o4.handle(_msg([_face()],
                           marcos_key="marcos/guid-o4.jpg",
                           definitivas_key="definitivas/guid-o4.jpg"))
            mock_db.update_solicitud_url_terminada.assert_called_once_with(
                o4.conn, "guid-o4", "definitivas/guid-o4.jpg"
            )
            mock_db.update_solicitud_url_marcos.assert_called_once_with(
                o4.conn, "guid-o4", "marcos/guid-o4.jpg"
            )

    def test_sets_fin_solicitud_timestamp(self):
        _setup()
        with patch("services.o4.main.db") as mock_db:
            o4.handle(_msg([]))
            calls = mock_db.update_solicitud_timestamps.call_args_list
            assert any("fin_solicitud" in str(c) for c in calls)

    def test_no_faces_still_marks_completada(self):
        _setup()
        with patch("services.o4.main.db") as mock_db:
            o4.handle(_msg([]))
            mock_db.update_imagen_age.assert_not_called()
            mock_db.update_solicitud_estado.assert_called_once_with(o4.conn, "guid-o4", "COMPLETADA")

    def test_db_exception_marks_fallida(self):
        _setup()
        with patch("services.o4.main.db") as mock_db:
            mock_db.update_imagen_age.side_effect = Exception("constraint violation")
            o4.handle(_msg([_face()]))
            mock_db.update_solicitud_estado.assert_called_with(o4.conn, "guid-o4", "FALLIDA")
