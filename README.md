# Proyecto Identificación y Pixelado de Rostros en Imágenes

Sistema distribuido basado en eventos (Event-Driven Architecture) que recibe imágenes vía HTTP REST, detecta rostros, estima la edad de cada uno y pixela automáticamente los rostros de personas menores de 18 años. La comunicación entre microservicios se realiza exclusivamente mediante **Kafka** (sin llamadas HTTP síncronas entre servicios).

---

## Tabla de contenidos

1. [Requisitos previos](#requisitos-previos)
2. [Estructura del repositorio](#estructura-del-repositorio)
3. [Descripción de servicios](#descripción-de-servicios)
4. [Flujo de eventos (topics Kafka)](#flujo-de-eventos-topics-kafka)
5. [Modelo de datos](#modelo-de-datos)
6. [Almacenamiento MinIO](#almacenamiento-minio)
7. [Cómo ejecutar el sistema](#cómo-ejecutar-el-sistema)
8. [API endpoints](#api-endpoints)
9. [Métricas de rendimiento](#métricas-de-rendimiento)
10. [Gestión de errores](#gestión-de-errores)
11. [Tests](#tests)

---

## Requisitos previos

- Docker y Docker Compose instalados
- Python 3.11

---

## Estructura del repositorio

```
proyecto_imagenes/
├── docker-compose.yml            # Orquestación de todos los contenedores
├── .env.example                  # Variables de entorno
├── README.md
│
├── docs/
│   ├── arquitectura.md           # Descripción detallada de la arquitectura
│   ├── flujo-eventos.md          # Contratos de cada topic Kafka
│   ├── gestion-errores.md        # Gestión de errores y propuestas de mejora
│   └── dashboard.md              # Diseño del dashboard Power BI (páginas, métricas, columnas y medidas)
│
├── powerbi/
│   └── sistema_deteccion_menores.pbix  # Dashboard Power BI
│
├── infra/
│   ├── kafka/                    # Script para crear los topics
│      └── create-topics.sh
│   ├── postgres/
│   │   └── init.sql              # Script para crear las tablas Solicitud e Imagenes
│   └── minio/
│       └── init-bucket.sh        # Script para crear el bucket y las carpetas en MinIO
│
├── shared/                       # Código compartido entre servicios
│   ├── kafka_client.py           # Wrappers de productor/consumidor (confluent-kafka)
│   ├── s3_client.py              # Wrapper sobre MinIO/S3 (boto3)
│   ├── db.py                     # Conexión a Postgres + helpers (psycopg2)
│   └── events/                   # Schemas JSON de todos los mensajes Kafka
│       ├── images.raw.send.json
│       ├── images.faces_detected.json
│       ├── images.faces_detected.send.json
│       ├── images.age_estimated.json
│       ├── images.age_estimated.send.json
│       └── images.processed.json
│
├── services/
│   ├── api_upload/               # API_1 / O1: recibe imagen, publica el evento inicial
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── main.py
│   ├── api_query/                # API_2: endpoints de consulta (lee BD + MinIO)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── main.py
│   ├── o2/                       # Orquestador 2: tras detección de caras
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── main.py
│   ├── o3/                       # Orquestador 3: tras estimación de edad
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── main.py
│   ├── o4/                       # Orquestador 4: cierra el pipeline
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── main.py
│   ├── dc/                       # Face Detection (YOLOv8 + OpenCV)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── main.py
│   ├── de/                       # Age Detection (PyTorch ResNet)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── main.py
│   └── pixelar/                  # Pixelation (OpenCV)
│       ├── Dockerfile
│       ├── requirements.txt
│       └── main.py
│
└── tests/
    ├── unit/                     # Tests unitarios por servicio
    └── integration/              # Flujo end-to-end con Kafka real
```

---

## Descripción de servicios


| Servicio     | Rol                                                                                                                                                                                                                                                                                                                                                            | Tecnología                    |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- |
| `api_upload` | **API_1 / O1** — Recibe la imagen vía `POST /images`, guarda el estado inicial en Postgres, sube la imagen original a MinIO y publica en `images.raw.send`                                                                                                                                                                                                     | FastAPI + psycopg2 + boto3    |
| `dc`         | **Face Detection** — Consume `images.raw.send`, detecta rostros con YOLOv8 y publica bounding boxes en `images.faces_detected`                                                                                                                                                                                                                                 | ultralytics (YOLOv8) + OpenCV |
| `o2`         | **Orquestador 2** — Consume `images.faces_detected`; si hay caras guarda los recortes en MinIO (`caras/`), inserta filas en `Imagenes` y publica `images.faces_detected.send`; si no hay caras cierra la solicitud directamente en BD y MinIO                                                                                                                  | psycopg2 + boto3              |
| `de`         | **Age Detection** — Consume `images.faces_detected.send`, clasifica cada cara como `<18` / `>=18` con una ResNet-50 entrenada sobre el dataset [facial-age (Kaggle)](https://www.kaggle.com/datasets/frabbisw/facial-age); el umbral de decisión se calcula en entrenamiento y se carga desde `age_threshold.json`; publica el score en `images.age_estimated` | PyTorch + ResNet-50           |
| `o3`         | **Orquestador 3** — Consume `images.age_estimated`; si hay menores publica `images.age_estimated.send` hacia Pixelar; si no hay menores genera la imagen con marcos y cierra la solicitud en BD y MinIO                                                                                                                                                        | psycopg2 + boto3              |
| `pixelar`    | **Pixelation** — Consume `images.age_estimated.send`, genera la imagen con bounding boxes y score (`marcos/`) y la imagen con caras de menores pixeladas (`definitivas/`), publica `images.processed`                                                                                                                                                          | OpenCV                        |
| `o4`         | **Orquestador 4** — Consume `images.processed`, escribe en BD y MinIO y marca la solicitud como `COMPLETADA`                                                                                                                                                                                                                                                   | psycopg2 + boto3              |
| `api_query`  | **API_2** — Endpoints de consulta; lee directamente de Postgres y MinIO, sin pasar por Kafka                                                                                                                                                                                                                                                                   | FastAPI + psycopg2 + boto3    |


---

## Flujo de eventos (topics Kafka)

```
Cliente
  │
  ▼ POST /images
api_upload (API_1/O1)
  │ guarda estado CREADA en Postgres, sube la imagen a MinIO
  │──► [images.raw.send]
          │
          ▼
         DC (Face Detection)
          │ detecta rostros con YOLOv8
          │──► [images.faces_detected]
                  │
                  ▼
                 O2
                  ├─ (sin caras) → escribe en BD y MinIO → COMPLETADA
                  └─ (con caras) → guarda recortes en caras/ → inserta Imagenes
                      │──► [images.faces_detected.send]
                              │
                              ▼
                             DE (Age Detection)
                              │ clasifica <18 / ≥18 con ResNet y score
                              │──► [images.age_estimated]
                                      │
                                      ▼
                                     O3
                                      ├─ (sin menores) → genera marcos/ → escribe en BD y MinIO → COMPLETADA
                                      └─ (con menores)
                                          │──► [images.age_estimated.send]
                                                  │
                                                  ▼
                                                 Pixelar
                                                  │ genera marcos/ (bboxes y score)
                                                  │ genera definitivas/ (pixelado)
                                                  │──► [images.processed]
                                                          │
                                                          ▼
                                                         O4
                                                          └─ escribe en BD y MinIO → COMPLETADA
```

### Topics y contratos


| Topic                        | Productor       | Consumidor | Semántica                             |
| ---------------------------- | --------------- | ---------- | ------------------------------------- |
| `images.raw.send`            | api_upload (O1) | DC         | Comando: iniciar detección de caras   |
| `images.faces_detected`      | DC              | O2         | Evento: detección de caras completada |
| `images.faces_detected.send` | O2              | DE         | Comando: iniciar estimación de edad   |
| `images.age_estimated`       | DE              | O3         | Evento: estimación de edad completada |
| `images.age_estimated.send`  | O3              | Pixelar    | Comando: iniciar pixelado             |
| `images.processed`           | Pixelar         | O4         | Evento: pixelado completado           |


Todos los mensajes incluyen `GUID_Solicitud` para trazabilidad end-to-end.

---

## Modelo de datos

```sql
CREATE TABLE Solicitud (
    GUID_Solicitud                VARCHAR(255) PRIMARY KEY,
    URL_Imagen_Original           VARCHAR(255),
    URL_Imagen_Terminada          VARCHAR(255),
    URL_Imagen_Marcos             VARCHAR(255),
    Inicio_Solicitud              TIMESTAMP,
    Fin_Solicitud                 TIMESTAMP,
    Inicio_Deteccion_Caras        TIMESTAMP,
    Fin_Deteccion_Caras           TIMESTAMP,
    Inicio_Edad                   TIMESTAMP,
    Fin_edad                      TIMESTAMP,
    Inicio_Pixelado               TIMESTAMP,
    Fin_Pixelado                  TIMESTAMP,
    Inicio_Almacenamiento_Solicitud TIMESTAMP,
    Fin_Almacenamiento_Solicitud  TIMESTAMP,
    Estado                        VARCHAR(50)
);

CREATE TABLE Imagenes (
    GUID_Solicitud  VARCHAR(255),
    Id_Imagen       INT,
    URL_Imagen      VARCHAR(255),
    Mayor_18        BOOLEAN,
    Score           DECIMAL(5,4),
    Imagen_X        INT,
    Imagen_Y        INT,
    Imagen_Ancho    INT,
    Imagen_Alto     INT,
    PRIMARY KEY (GUID_Solicitud, Id_Imagen),
    FOREIGN KEY (GUID_Solicitud) REFERENCES Solicitud(GUID_Solicitud)
);
```

**Estados de `Solicitud`:**
`CREADA` → `CARAS_DETECTADAS` → `EDAD_CALCULADA` → `COMPLETADA`

`FALLIDA` Se signa cuando el consumer encuentra una expeción no recuperable en el procesamiento de un mensaje.

---

## Almacenamiento MinIO

Bucket único: `images`


| Carpeta                        | Contenido                                                 |
| ------------------------------ | --------------------------------------------------------- |
| `originales/{guid}.{ext}`      | Imagen original subida por el cliente                     |
| `caras/{guid}/{id_imagen}.jpg` | Recorte individual de cada cara detectada                 |
| `marcos/{guid}.jpg`            | Imagen completa con bounding boxes y score (sin pixelado) |
| `definitivas/{guid}.jpg`       | Imagen completa con las caras de menores pixeladas        |


---

## Cómo ejecutar el sistema

### 1. Configurar variables de entorno

```bash
cp .env.example .env
```

### 2. Levantar todos los servicios

```bash
docker compose up -d
```

### 3. Ver que todo está en marcha

```bash
docker compose ps
docker compose logs -f api_upload
```

### 4. Flujo de prueba rápido

```bash
# Subir una imagen
curl -X POST http://localhost:8000/images -F "file=@foto.jpg"
# → devuelve { "guid": "<GUID>" }

# Consultar el estado de la solicitud
curl http://localhost:8000/solicitudes/<GUID>

# Consultar una cara concreta
curl http://localhost:8000/caras/<GUID>/0
```

### 5. MinIO

Accede a `http://localhost:9011` con las credenciales definidas en `.env` para ver las imágenes almacenadas (la API S3 escucha en el puerto `9010`).

### Comandos útiles

```bash
# Ver los logs de un servicio específico
docker compose logs -f face_detection

# Reconstruir un servicio tras cambios en el código
docker compose up -d --build face_detection

# Ejecutar todos los tests
pytest tests/

# Ejecutar tests unitarios de un servicio
pytest tests/unit/test_face_detection.py

# Ejecutar tests de integración
pytest tests/integration/

```

---

## API endpoints

### POST `/images`

Sube una imagen para el procesamiento.

- **Body**: `multipart/form-data` con campo `file`
- **Response 202**: `{ "guid": "<GUID_Solicitud>" }`

### GET `/solicitudes/{guid}`

Devuelve los metadatos completos de la solicitud.

- **Response 200**: objeto con `Estado`, URLs de imágenes, timestamps por fase y lista de caras detectadas
- **Response 404**: solicitud no encontrada

### GET `/caras/{guid}/{id}`

Devuelve los metadatos e imagen de la cara concreta.

- **Response 200**: objeto con `Mayor_18`, `Score`, bounding box y URL de la imagen del recorte
- **Response 404**: solicitud o cara no encontrada

---

## Métricas de rendimiento

Cada servicio se registra en logs (JSON):


| Métrica       | Descripción                                                          |
| ------------- | -------------------------------------------------------------------- |
| `duration_ms` | Tiempo de procesamiento por evento (desde consumo hasta publicación) |
| `service`     | Nombre del servicio que genera el log                                |
| `guid`        | `GUID_Solicitud` para la correlación                                 |


La **latencia end-to-end** se calcula como `Fin_Solicitud - Inicio_Solicitud` en la tabla `Solicitud` una vez que O4 marca la solicitud como `COMPLETADA`.

---

## Gestión de errores

- Cada consumer Kafka envuelve el procesamiento en `try/except`: si falla, loguea el error estructurado y marca `Solicitud.Estado = FALLIDA` en Postgres.
- El offset se confirma aunque el procesamiento falle para no bloquear el topic.
- Los contenedores declaran health checks en `docker-compose.yml` para garantizar el orden de arranque.

**Propuestas de mejora**:

- **Dead Letter Queue (DLQ)** — mensajes que fallan repetidamente se redirigen a un topic aparte para inspección manual.
- **Reintentos con backoff exponencial** — ante errores transitorios reintenta antes de marcar la solicitud como `FALLIDA` (p. ej. con `tenacity`).
- **Idempotencia de consumers** — garantizar que reprocesar un mensaje dos veces no genere filas duplicadas en `Imagenes` (`INSERT ... ON CONFLICT DO NOTHING`).
- **Circuit breaker** — si un servicio downstream falla repetidamente, dejar de enviarle mensajes temporalmente para no saturar el sistema.
- **Reconexión automática a Postgres** — usar un pool de conexiones (`psycopg2.pool`) con reconexión automática en lugar de una única conexión por servicio.
- **Alertas y monitorización** — integrar los logs estructurados con Prometheus + Grafana para dashboards de latencia, alertas de tasa de fallo y throughput del pipeline.
- **Revisión humana en casos ambiguos** — solicitudes con score en zona de incertidumbre (p.ej. 0.4–0.6) podrían quedar en estado `PENDIENTE_REVISION`.
- **Sesgo demográfico del modelo** — el modelo tiende a subestimar la edad en determinados grupos étnicos. Propuesta: incorporar un clasificador étnico previo y aplicar un estimador de edad calibrado por grupo.

---

## Stack tecnológico


| Componente     | Tecnología                                                                                            |
| -------------- | ----------------------------------------------------------------------------------------------------- |
| Lenguaje       | Python 3.11                                                                                           |
| API            | FastAPI                                                                                               |
| Mensajería     | Apache Kafka 3.8.0 (KRaft, imagen `apache/kafka`)                                                     |
| Face Detection | YOLOv8 (`ultralytics`) + OpenCV                                                                       |
| Age Detection  | PyTorch + ResNet — dataset [facial-age (Kaggle)](https://www.kaggle.com/datasets/frabbisw/facial-age) |
| Pixelación     | OpenCV                                                                                                |
| Base de datos  | PostgreSQL (`psycopg2`)                                                                               |
| Almacenamiento | MinIO compatible S3 (`boto3`)                                                                         |
| Kafka client   | `confluent-kafka-python`                                                                              |
| Dashboard      | Power BI Desktop                                                                                      |


#   D e t e c c i - n _ y _ p i x e l a d o _ d e _ c a r a s 
 
 #   D e t e c c i - n _ y _ p i x e l a d o _ d e _ c a r a s 
 
 #   D e t e c c i o n Y P i x e l a d o D e I m a g e n e s 
 
 