import pytest
from unittest.mock import MagicMock, call, patch
from contextlib import contextmanager
from shared import db

@pytest.fixture
def conn():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn

def _cur(conn):
    return conn.cursor.return_value.__enter__.return_value

class TestCreateSolicitud:
    def test_execute_called(self, conn):
        db.create_solicitud(conn, "guid-1", "http://minio/img.jpg")
        _cur(conn).execute.assert_called_once()

    def test_guid_in_params(self, conn):
        db.create_solicitud(conn, "guid-1", "http://minio/img.jpg")
        args = _cur(conn).execute.call_args[0]
        assert "guid-1" in args[1]

    def test_url_in_params(self, conn):
        db.create_solicitud(conn, "guid-1", "http://minio/img.jpg")
        args = _cur(conn).execute.call_args[0]
        assert "http://minio/img.jpg" in args[1]

    def test_insert_into_solicitud_in_sql(self, conn):
        db.create_solicitud(conn, "guid-1", "http://minio/img.jpg")
        sql = _cur(conn).execute.call_args[0][0]
        assert "INSERT INTO Solicitud" in sql

    def test_commit_called(self, conn):
        db.create_solicitud(conn, "guid-1", "http://minio/img.jpg")
        conn.commit.assert_called_once()

class TestUpdateSolicitudEstado:
    def test_execute_called(self, conn):
        db.update_solicitud_estado(conn, "guid-1", "COMPLETADA")
        _cur(conn).execute.assert_called_once()

    def test_estado_in_params(self, conn):
        db.update_solicitud_estado(conn, "guid-1", "COMPLETADA")
        args = _cur(conn).execute.call_args[0]
        assert "COMPLETADA" in args[1]
        assert "guid-1" in args[1]

class TestGetSolicitud:
    def test_returns_fetchone_result(self, conn):
        _cur(conn).fetchone.return_value = {"GUID_Solicitud": "g1"}
        result = db.get_solicitud(conn, "g1")
        assert result == {"GUID_Solicitud": "g1"}

    def test_returns_none_when_not_found(self, conn):
        _cur(conn).fetchone.return_value = None
        result = db.get_solicitud(conn, "missing")
        assert result is None

    def test_guid_passed_as_param(self, conn):
        _cur(conn).fetchone.return_value = None
        db.get_solicitud(conn, "my-guid")
        args = _cur(conn).execute.call_args[0]
        assert "my-guid" in args[1]

class TestInsertImagen:
    def test_execute_called(self, conn):
        db.insert_imagen(conn, "g1", 0, "def/g1/0.jpg", True, 0.9, 10, 20, 30, 40)
        _cur(conn).execute.assert_called_once()

    def test_all_values_in_params(self, conn):
        db.insert_imagen(conn, "g1", 2, "def/g1/2.jpg", False, 0.75, 5, 6, 50, 60)
        args = _cur(conn).execute.call_args[0]
        params = args[1]
        assert "g1" in params
        assert 2 in params
        assert "def/g1/2.jpg" in params
        assert False in params
        assert 0.75 in params
        assert 5 in params

    def test_insert_into_imagenes_in_sql(self, conn):
        db.insert_imagen(conn, "g1", 0, "url", True, 0.1, 0, 0, 10, 10)
        sql = _cur(conn).execute.call_args[0][0]
        assert "INSERT INTO Imagenes" in sql

class TestGetImagenes:
    def test_returns_list(self, conn):
        rows = [{"Id_Imagen": 0}, {"Id_Imagen": 1}]
        _cur(conn).fetchall.return_value = rows
        result = db.get_imagenes(conn, "g1")
        assert result == rows

    def test_returns_empty_list_when_none(self, conn):
        _cur(conn).fetchall.return_value = []
        result = db.get_imagenes(conn, "g1")
        assert result == []

class TestGetImagen:
    def test_returns_row(self, conn):
        row = {"Id_Imagen": 3, "Score": 0.8}
        _cur(conn).fetchone.return_value = row
        result = db.get_imagen(conn, "g1", 3)
        assert result == row

    def test_id_imagen_passed_as_param(self, conn):
        _cur(conn).fetchone.return_value = None
        db.get_imagen(conn, "g1", 7)
        args = _cur(conn).execute.call_args[0]
        assert 7 in args[1]

class TestCursorRollback:
    def test_rollback_called_on_exception(self, conn):
        _cur(conn).execute.side_effect = Exception("SQL error")
        with pytest.raises(Exception, match="SQL error"):
            db.create_solicitud(conn, "g", "url")
        conn.rollback.assert_called_once()

    def test_commit_not_called_on_exception(self, conn):
        _cur(conn).execute.side_effect = Exception("SQL error")
        with pytest.raises(Exception):
            db.create_solicitud(conn, "g", "url")
        conn.commit.assert_not_called()
