# Gestion de Errores

## Estrategia implementada

### Patron general: try/except por consumer

Cada servicio que consume de Kafka envuelve el procesamiento de cada mensaje en un bloque `try/except`. Ante una excepcion no recuperable:

1. Se registra el error completo en logs estructurados
2. Se actualiza `Solicitud.Estado = FALLIDA` en Postgres
3. Se confirma el offset del mensaje en Kafka

```python
def handle(msg: dict):
    guid = msg["GUID_Solicitud"]
    try:

    except Exception:
        logger.exception("Error en handle, guid=%s", guid)
        db.update_solicitud_estado(conn, guid, "FALLIDA")
```

Este patron se aplica en los orquestadores **O2**, **O3** y **O4**. Los servicios de procesamiento (DC, DE, Pixelar) no acceden a la BD, por lo que un fallo en ellos provoca que el mensaje no se propague al siguiente topic y el pipeline queda detenido para esa solicitud.

### Commit de offset incondicional

El consumer confirma el offset del mensaje **siempre**, tanto si el procesamiento tiene exito como si falla:

```python
try:
    data = json.loads(msg.value().decode())
    handler(data)
except Exception as exc:
    logger.exception("Handler raised exception: %s", exc)
finally:
    self._consumer.commit(message=msg)
```

Esto evita que un mensaje problematico bloquee al consumer group indefinidamente. El coste es que si un mensaje falla, no se reintenta automaticamente: el fallo se registra en BD como `FALLIDA` y en los logs del servicio.

### Health checks de infraestructura

En `docker-compose.yml`, todos los contenedores de servicios declaran `depends_on` con `condition: service_healthy` sobre Kafka, Postgres y MinIO. Ademas, los contenedores de inicializacion (`kafka-init`, `minio-init`) deben completarse antes de que los servicios arranquen.

Esto garantiza que:

- Los topics existen antes de que los consumers intenten suscribirse
- El bucket de MinIO esta creado antes de que los servicios intenten leer/escribir
- Postgres tiene las tablas creadas antes de las primeras inserciones

### Estado `FALLIDA`

Añadimos el estado `FALLIDA` para representar solicitudes cuyo procesamiento encontró un error no recuperable.

Una solicitud en estado `FALLIDA` no se reintenta automaticamente. Se puede consultar via la API de consulta (`GET /solicitudes/{guid}`) para ver en que fase quedo detenida (revisando los timestamps rellenados y los que quedaron nulos).

## Posibles casos de fallo y comportamiento

### Fallo en DC (Face Detection)

- **Causa tipica**: imagen corrupta o formato no soportado
- **Comportamiento**: DC publica `images.faces_detected` con `faces: []` si no puede decodificar la imagen. O2 lo interpreta como "sin caras" y cierra la solicitud como `COMPLETADA`.
- **Si DC lanza una excepcion no capturada**: el mensaje se confirma igualmente, pero no se publica ningun evento. La solicitud queda en estado `CREADA` indefinidamente.

### Fallo en DE (Age Detection)

- **Causa tipica**: cara con dimensiones muy pequenas que el modelo no puede procesar
- **Comportamiento**: DE captura el error por cara individual y asigna `score = 0.0` (no menor). El procesamiento continua con las demas caras.
- **Si DE lanza una excepcion global**: no se publica en `images.age_estimated`. La solicitud queda en estado `CARAS_DETECTADAS`.

### Fallo en Pixelar

- **Causa tipica**: imagen no encontrada en MinIO (borrado manual o inconsistencia)
- **Comportamiento**: no se publica en `images.processed`. La solicitud queda en estado `EDAD_CALCULADA`.

### Fallo en un orquestador (O2, O3, O4)

- **Comportamiento**: el bloque `except` captura la excepcion, marca la solicitud como `FALLIDA` en BD y loguea el error. El pipeline se detiene para esa solicitud.

### Fallo de infraestructura (Kafka, Postgres, MinIO caido)

- **Kafka caido**: los consumers bloqueados en `poll()` no reciben mensajes. Al restaurarse Kafka, reanudan desde el ultimo offset confirmado.
- **Postgres caido**: la escritura a BD falla con excepcion, se activa el patron try/except. Si la conexion se pierde permanentemente, el servicio deja de procesar hasta reiniciarse.
- **MinIO caido**: la lectura/escritura de imagenes falla con excepcion. Mismo comportamiento que Postgres.

## Propuestas de mejora

### 1. Modelos especializados por grupo etnico

Entrenar un modelo de estimacion de edad especializado por grupo etnico, enriquecido con datasets de diversidad racial como UTKFace o FairFace. Un clasificador previo detectaria la etnia y enrutaria la estimacion al modelo correspondiente, eliminando el sesgo que aparece cuando un unico modelo intenta aprender patrones de edad de poblaciones con caracteristicas faciales distintas.

### 2. Data augmentation de apariencia

Incorporar augmentation de maquillaje, cremas e iluminacion durante el entrenamiento de cada modelo especializado, de forma que aprenda estructura facial independientemente de la apariencia en el momento de la foto.

### 3. Alertas en tiempo real para solicitudes fallidas

Integrar un canal de notificaciones (Slack, email o webhook) que se dispare cuando una solicitud queda en estado `FALLIDA`. Actualmente el fallo queda registrado en Postgres y en logs, pero nadie lo sabe en tiempo real. Con alertas, un operador puede detectar y corregir un servicio caido antes de que se acumulen errores.