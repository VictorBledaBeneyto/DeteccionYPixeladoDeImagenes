# Arquitectura del Sistema

## Visión general

El sistema sigue una **Arquitectura Event-Driven** donde los microservicios se comunican exclusivamente a través de **Apache Kafka**. No existen llamadas HTTP entre servicios: cada servicio consume mensajes de un topic, realiza su procesamiento y publica el resultado en otro topic. Un conjunto de **orquestadores** (O1-O4) coordina el flujo del pipeline, decidiendo el siguiente paso en función del estado de la imagen.

```
                                   ┌──────────┐
                        ┌─────────►│    O4    │──► BD (COMPLETADA)
                        │          └──────────┘
                   [images.processed]
                        │
                  ┌─────┴─────┐
                  │  Pixelar  │──► MinIO (marcos/ + definitivas/)
                  └─────┬─────┘
                        │
              [images.age_estimated.send]
                        │
                  ┌─────┴─────┐
         ┌───────│    O3      │───────┐
         │       └────────────┘       │
    (con menores)               (sin menores)
         │                       → genera marcos/
         │                       → BD + MinIO
         │                       → COMPLETADA
   [images.age_estimated]
         │
   ┌─────┴─────┐
   │    DE     │  Age Detection (ResNet)
   └─────┬─────┘
         │
  [images.faces_detected.send]
         │
   ┌─────┴─────┐
   │    O2     │──► MinIO (caras/) + BD (Imagenes)
   └─────┬─────┘
         │       └─ (sin caras) → BD + MinIO → COMPLETADA
         │
   [images.faces_detected]
         │
   ┌─────┴─────┐
   │    DC     │  Face Detection (YOLOv8)
   └─────┬─────┘
         │
    [images.raw.send]
         │
   ┌─────┴──────┐
   │ api_upload  │  API_1 / O1
   │  (FastAPI)  │──► Postgres (CREADA) + MinIO (originales/)
   └─────┬──────┘
         │
    POST /images
         │
   ┌─────┴──────┐        ┌────────────┐
   │  Cliente   │        │ api_query  │  GET /solicitudes/{guid}
   └────────────┘        │  (FastAPI)  │  GET /caras/{guid}/{id}
                         └────────────┘
                              │
                         Postgres + MinIO (lectura directa)
```

## Contenedores Docker

El sistema se despliega con `docker compose` y consta de **11 contenedores** (8 servicios propios + 3 de infraestructura):

### Infraestructura


| Contenedor   | Imagen               | Función                                    |
| ------------ | -------------------- | ------------------------------------------ |
| `kafka`      | `apache/kafka:3.8.0` | Broker Kafka en modo KRaft (sin Zookeeper) |
| `kafka-init` | `apache/kafka:3.8.0` | Crea los 6 topics al arrancar y termina    |
| `postgres`   | `postgres:16-alpine` | Base de datos relacional                   |
| `minio`      | `minio/minio:latest` | Almacenamiento de objetos compatible S3    |
| `minio-init` | `minio/mc:latest`    | Crea el bucket `images` y termina          |


### Servicios de aplicacion


| Contenedor   | Servicio       | Consume                      | Produce                      |
| ------------ | -------------- | ---------------------------- | ---------------------------- |
| `api_upload` | API_1 / O1     | HTTP `POST /images`          | `images.raw.send`            |
| `dc`         | Face Detection | `images.raw.send`            | `images.faces_detected`      |
| `o2`         | Orquestador 2  | `images.faces_detected`      | `images.faces_detected.send` |
| `de`         | Age Detection  | `images.faces_detected.send` | `images.age_estimated`       |
| `o3`         | Orquestador 3  | `images.age_estimated`       | `images.age_estimated.send`  |
| `pixelar`    | Pixelation     | `images.age_estimated.send`  | `images.processed`           |
| `o4`         | Orquestador 4  | `images.processed`           | (cierra pipeline)            |
| `api_query`  | API_2          | (sin Kafka)                  | (sin Kafka)                  |


### Dependencias de arranque

Todos los servicios declaran `depends_on` con `condition: service_healthy` sobre Kafka, Postgres y MinIO. Los contenedores `kafka-init` y `minio-init` se ejecutan como `service_completed_successfully` antes de que arranquen los servicios.

## Descripcion detallada de cada servicio

### api_upload (API_1 / O1)

- **Puerto**: 8000
- **Framework**: FastAPI
- **Responsabilidad**: punto de entrada HTTP. Recibe la imagen, genera un GUID, la sube a `originales/{guid}.{ext}` en MinIO, crea la fila en `Solicitud` con estado `CREADA` y publica el mensaje en `images.raw.send`.
- **Patron**: Actua simultaneamente como API Gateway y como Orquestador 1 (O1), embebidos en un mismo contenedor.

### dc (Face Detection)

- **Modelo**: YOLOv8n-face (`yolov8n-face.pt`)
- **Responsabilidad**: descarga la imagen original de MinIO, ejecuta la deteccion de rostros y publica las bounding boxes (`x, y, w, h`) en `images.faces_detected`.
- **Sin acceso a BD**: DC solo lee de MinIO y publica en Kafka.

### o2 (Orquestador 2)

- **Responsabilidad**: tras la deteccion de caras, decide el siguiente paso:
  - **Con caras**: recorta cada cara de la imagen original, sube cada recorte a `caras/{guid}/{id}.jpg` en MinIO, inserta filas en la tabla `Imagenes` y publica `images.faces_detected.send`.
  - **Sin caras**: cierra la solicitud directamente: marca `COMPLETADA` en BD y asigna la imagen original como `URL_Imagen_Terminada`.

### de (Age Detection)

- **Modelo**: ResNet-50 entrenado sobre el dataset [facial-age (Kaggle)](https://www.kaggle.com/datasets/frabbisw/facial-age). Clasificador binario `<18 / >=18` con salida sigmoid.
- **Responsabilidad**: para cada cara, recorta la region de la imagen original, la pasa por el modelo y obtiene un `Score` (probabilidad de ser menor). Si `Score > THRESHOLD`, `es_menor = true`.
- **Umbral**: no es fijo en 0.5. El notebook `train_classifier.ipynb` calcula el umbral óptimo que maximiza el F1-score de la clase "Menor" sobre el conjunto de validación y lo persiste en `age_threshold.json`. El servicio carga ese fichero al arrancar.
- **Sin acceso a BD**: DE solo lee de MinIO y publica en Kafka.

### o3 (Orquestador 3)

- **Responsabilidad**: tras la estimacion de edad, decide el siguiente paso:
  - **Con menores**: publica `images.age_estimated.send` para que Pixelar procese la imagen.
  - **Sin menores**: genera la imagen con marcos (bounding boxes + score superpuesto) y guarda `marcos/{guid}.jpg` y `definitivas/{guid}.jpg` (copia sin pixelar) en MinIO. Actualiza `Mayor_18` y `Score` en `Imagenes`, marca `COMPLETADA`.

### pixelar (Pixelation)

- **Responsabilidad**: genera dos imagenes separadas:
  1. `marcos/{guid}.jpg`: imagen original con bounding boxes de **todas** las caras y el score del modelo superpuesto. Color rojo para menores, verde para mayores.
  2. `definitivas/{guid}.jpg:` imagen original con las caras de **menores pixeladas**.
- **Factor de pixelado**: configurable via variable de entorno `PIXELATION_FACTOR`.
- Publica ambas claves S3 en `images.processed`.

### o4 (Orquestador 4)

- **Responsabilidad**: paso final del pipeline. Actualiza `Mayor_18` y `Score` en cada fila de `Imagenes`, asigna `URL_Imagen_Terminada` y `URL_Imagen_Marcos`, rellena los timestamps de finalizacion y marca la solicitud como `COMPLETADA`.

### api_query (API_2)

- **Puerto**: 8001
- **Framework**: FastAPI
- **Responsabilidad**: endpoints de solo lectura. Lee directamente de Postgres y MinIO, sin participar en el flujo Kafka.
- **Endpoints**:
  - `GET /solicitudes/{guid}`: metadatos de la solicitud + lista de caras
  - `GET /caras/{guid}/{id}`: metadatos de una cara concreta

## Stack tecnologico


| Componente     | Tecnologia                      |
| -------------- | ------------------------------- |
| Lenguaje       | Python 3.11                     |
| API            | FastAPI                         |
| Mensajeria     | Apache Kafka 3.8.0 (KRaft)      |
| Kafka client   | `confluent-kafka-python`        |
| Face Detection | YOLOv8 (`ultralytics`) + OpenCV |
| Age Detection  | PyTorch + ResNet-50             |
| Pixelado       | OpenCV                          |
| Base de datos  | PostgreSQL 16 (`psycopg2`)      |
| Almacenamiento | MinIO (`boto3`, compatible S3)  |
| Contenedores   | Docker Compose                  |


## Codigo compartido (`shared/`)

Los servicios comparten tres modulos ubicados en `shared/`, montados como volumen en cada contenedor:

- `**kafka_client.py`**:`KafkaProducer` y `KafkaConsumer` sobre `confluent-kafka`. El consumer utiliza commit manual de offsets (se confirma despues de cada mensaje, haya exito o error).
- `**s3_client.py`**: `S3Client` sobre `boto3`. Operaciones: `upload_bytes`, `download_bytes`, `object_exists`.
- `**db.py**`: conexion y helpers para Postgres: CRUD de `Solicitud` e `Imagenes`, actualizacion de timestamps y estados.

## Red y puertos

Todos los contenedores estan en la red Docker `backend` (bridge). Los puertos expuestos al host son:


| Puerto host | Servicio   | Descripcion                        |
| ----------- | ---------- | ---------------------------------- |
| 8000        | api_upload | API REST para subir imagenes       |
| 8001        | api_query  | API REST para consultar resultados |
| 9092        | kafka      | Broker Kafka                       |
| 5432        | postgres   | PostgreSQL                         |
| 9010        | minio      | MinIO API (S3)                     |
| 9011        | minio      | MinIO Console (web UI)             |


