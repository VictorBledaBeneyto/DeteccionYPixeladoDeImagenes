import logging
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

logger = logging.getLogger(__name__)

def get_connection(host: str, port: int, dbname: str, user: str, password: str):
    return psycopg2.connect(
        host=host, port=port, dbname=dbname, user=user, password=password
    )

@contextmanager
def cursor(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise

def create_solicitud(conn, guid: str, url: str) -> None:
    with cursor(conn) as cur:
        cur.execute(
            """
            INSERT INTO Solicitud (GUID_Solicitud, URL_Imagen_Original, Inicio_Solicitud, Estado)
            VALUES (%s, %s, NOW(), 'CREADA')
            """,
            (guid, url),
        )

def update_solicitud_estado(conn, guid: str, estado: str) -> None:
    with cursor(conn) as cur:
        cur.execute(
            "UPDATE Solicitud SET Estado = %s WHERE GUID_Solicitud = %s",
            (estado, guid),
        )

def update_solicitud_timestamps(conn, guid: str, **fields) -> None:
    from psycopg2 import sql as pgsql

    parts = []
    values = []
    for col, val in fields.items():
        if val == "NOW()":
            parts.append(pgsql.SQL("{} = NOW()").format(pgsql.Identifier(col)))
        else:
            parts.append(pgsql.SQL("{} = %s").format(pgsql.Identifier(col)))
            values.append(val)
    values.append(guid)

    query = pgsql.SQL("UPDATE Solicitud SET {} WHERE GUID_Solicitud = %s").format(
        pgsql.SQL(", ").join(parts)
    )
    with cursor(conn) as cur:
        cur.execute(query, values)

def get_solicitud(conn, guid: str) -> dict | None:
    with cursor(conn) as cur:
        cur.execute("SELECT * FROM Solicitud WHERE GUID_Solicitud = %s", (guid,))
        return cur.fetchone()

def update_solicitud_url_terminada(conn, guid: str, url: str | None) -> None:
    with cursor(conn) as cur:
        cur.execute(
            "UPDATE Solicitud SET URL_Imagen_Terminada = %s WHERE GUID_Solicitud = %s",
            (url, guid),
        )

def update_solicitud_url_marcos(conn, guid: str, url: str | None) -> None:
    with cursor(conn) as cur:
        cur.execute(
            "UPDATE Solicitud SET URL_Imagen_Marcos = %s WHERE GUID_Solicitud = %s",
            (url, guid),
        )

def insert_imagen(conn, guid: str, id_imagen: int, url_imagen: str, mayor_18: bool, score: float,
                  x: int, y: int, ancho: int, alto: int) -> None:
    with cursor(conn) as cur:
        cur.execute(
            """
            INSERT INTO Imagenes
                (GUID_Solicitud, Id_Imagen, URL_Imagen, Mayor_18, Score, Imagen_X, Imagen_Y, Imagen_Ancho, Imagen_Alto)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (guid, id_imagen, url_imagen, mayor_18, score, x, y, ancho, alto),
        )

def update_imagen_age(conn, guid: str, id_imagen: int, mayor_18: bool, score: float) -> None:
    with cursor(conn) as cur:
        cur.execute(
            """
            UPDATE Imagenes SET Mayor_18 = %s, Score = %s
            WHERE GUID_Solicitud = %s AND Id_Imagen = %s
            """,
            (mayor_18, score, guid, id_imagen),
        )

def get_imagenes(conn, guid: str) -> list[dict]:
    with cursor(conn) as cur:
        cur.execute("SELECT * FROM Imagenes WHERE GUID_Solicitud = %s ORDER BY Id_Imagen", (guid,))
        return cur.fetchall()

def get_imagen(conn, guid: str, id_imagen: int) -> dict | None:
    with cursor(conn) as cur:
        cur.execute(
            "SELECT * FROM Imagenes WHERE GUID_Solicitud = %s AND Id_Imagen = %s",
            (guid, id_imagen),
        )
        return cur.fetchone()
