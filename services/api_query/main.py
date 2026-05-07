import os
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from shared import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("api_query")

app = FastAPI(title="API Query - Proyecto Imagenes")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_CONN_PARAMS = dict(
    host=os.environ["POSTGRES_HOST"],
    port=int(os.environ["POSTGRES_PORT"]),
    dbname=os.environ["POSTGRES_DB"],
    user=os.environ["POSTGRES_USER"],
    password=os.environ["POSTGRES_PASSWORD"],
)

conn = db.get_connection(**DB_CONN_PARAMS)


@app.get("/solicitudes/{guid}")
def get_solicitud(guid: str):
    solicitud = db.get_solicitud(conn, guid)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    imagenes = db.get_imagenes(conn, guid)
    return {"solicitud": dict(solicitud), "imagenes": [dict(i) for i in imagenes]}


@app.get("/caras/{guid}/{id_imagen}")
def get_cara(guid: str, id_imagen: int):
    imagen = db.get_imagen(conn, guid, id_imagen)
    if not imagen:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")
    return dict(imagen)


@app.get("/health")
def health():
    return {"status": "ok"}
