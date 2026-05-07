# Flujo de Eventos

## Topics Kafka

El sistema utiliza 6 topics de Kafka. Los topics con `.send` representan **comandos** del orquestador (ordenes de procesamiento). Los topics sin ese sufijo representan **eventos** (resultados de un servicio).


| Topic                        | Productor       | Consumidor | Semantica                             |
| ---------------------------- | --------------- | ---------- | ------------------------------------- |
| `images.raw.send`            | api_upload (O1) | DC         | Comando: iniciar deteccion de caras   |
| `images.faces_detected`      | DC              | O2         | Evento: deteccion de caras completada |
| `images.faces_detected.send` | O2              | DE         | Comando: iniciar estimacion de edad   |
| `images.age_estimated`       | DE              | O3         | Evento: estimacion de edad completada |
| `images.age_estimated.send`  | O3              | Pixelar    | Comando: iniciar pixelado             |
| `images.processed`           | Pixelar         | O4         | Evento: pixelado completado           |


Todos los mensajes incluyen `GUID_Solicitud` como key para garantizar el orden dentro de una solicitud.

## Flujo completo paso a paso

### Cliente sube imagen

```
Cliente → POST /images (multipart/form-data) → api_upload
```

`api_upload` (API_1/O1):

1. Genera un UUID como `GUID_Solicitud`
2. Sube la imagen a MinIO: `originales/{guid}.{ext}`
3. Inserta fila en `Solicitud` con `Estado = CREADA` y `Inicio_Solicitud = NOW()`
4. Registra `Inicio_Deteccion_Caras = NOW()`
5. Publica en `images.raw.send`
6. Devuelve `202 Accepted` con el GUID

### Deteccion de caras (DC)

```
[images.raw.send] → DC → [images.faces_detected]
```

DC (Face Detection):

1. Descarga la imagen original de MinIO usando `s3_key`
2. Ejecuta YOLOv8n-face para detectar rostros
3. Extrae las bounding boxes `(x, y, w, h)` de cada cara detectada
4. Publica la lista de caras (puede estar vacia) en `images.faces_detected`

### Orquestador O2 decide

```
[images.faces_detected] → O2
```

O2 actualiza `Fin_Deteccion_Caras = NOW()` y `Estado = CARAS_DETECTADAS`. Despues bifurca:

**Camino A - Sin caras detectadas:**

- Asigna `URL_Imagen_Terminada` = clave S3 de la imagen original
- Marca timestamps de almacenamiento y `Fin_Solicitud`
- `Estado = COMPLETADA`
- No publica ningun mensaje (fin del pipeline)

**Camino B - Con caras detectadas:**

- Descarga la imagen original de MinIO
- Recorta cada cara y la sube a `caras/{guid}/{id_imagen}.jpg`
- Inserta una fila por cara en la tabla `Imagenes` (sin `Mayor_18` ni `Score` todavia)
- Registra `Inicio_Edad = NOW()`
- Publica en `images.faces_detected.send`

### Estimacion de edad (DE)

```
[images.faces_detected.send] → DE → [images.age_estimated]
```

DE (Age Detection):

1. Descarga la imagen original de MinIO
2. Para cada cara, recorta la region del bounding box
3. Pasa el recorte por ResNet-50 (clasificador binario: menor vs. mayor)
4. Aplica sigmoid al logit para obtener `Score` (probabilidad de ser menor)
5. Si `Score > 0.5`, marca `es_menor = true`
6. Publica todas las caras con `score` y `es_menor` en `images.age_estimated`

### Orquestador O3 decide

```
[images.age_estimated] → O3
```

O3 actualiza `Fin_edad = NOW()` y `Estado = EDAD_CALCULADA`. Despues bifurca:

**Camino A - Sin menores:**

- Descarga la imagen original de MinIO
- Genera `marcos/{guid}.jpg` dibujando bounding boxes y scores sobre todas las caras
- Guarda `definitivas/{guid}.jpg` como copia sin pixelar de la original
- Actualiza `Mayor_18` y `Score` en cada fila de `Imagenes`
- Asigna URLs de marcos y definitivas en `Solicitud`
- Marca timestamps y `Estado = COMPLETADA`
- No publica ningun mensaje (fin del pipeline)

**Camino B - Con menores:**

- Registra `Inicio_Pixelado = NOW()`
- Publica en `images.age_estimated.send` con todas las caras (menores y mayores)

### Pixelado (Pixelar)

```
[images.age_estimated.send] → Pixelar → [images.processed]
```

Pixelar:

1. Descarga la imagen original de MinIO
2. Genera `marcos/{guid}.jpg`: copia de la original con bounding boxes (rojo para menores, verde para mayores) y el score superpuesto en cada cara
3. Genera `definitivas/{guid}.jpg`: copia de la original con las caras de menores pixeladas (resize down/up con `INTER_NEAREST`) — sin marcos ni bounding boxes
4. Sube ambas imagenes a MinIO
5. Publica en `images.processed` con las claves S3 de marcos y definitivas

### Orquestador O4 cierra

```
[images.processed] → O4
```

O4:

1. Actualiza `Mayor_18` y `Score` en cada fila de `Imagenes`
2. Asigna `URL_Imagen_Terminada` y `URL_Imagen_Marcos` en `Solicitud`
3. Registra `Fin_Pixelado`, `Inicio/Fin_Almacenamiento_Solicitud` y `Fin_Solicitud`
4. `Estado = COMPLETADA`

### Consulta de resultados (API_2)

```
Cliente → GET /solicitudes/{guid} → api_query → Postgres
Cliente → GET /caras/{guid}/{id}  → api_query → Postgres
```

`api_query` no participa en el flujo de eventos. Lee directamente de Postgres para devolver metadatos y URLs. El cliente puede usar las URLs de MinIO para descargar las imagenes.

## Resumen de caminos del pipeline

```
                          ┌── Sin caras ─────────────────────────── COMPLETADA (O2)
                          │
POST /images → DC → O2 ──┤
                          │              ┌── Sin menores ────────── COMPLETADA (O3)
                          └── Con caras ─┤
                                         └── Con menores → Pixelar → COMPLETADA (O4)
```

Existen tres caminos posibles hasta `COMPLETADA`:

1. **Sin caras**: O2 cierra directamente (no se ejecutan DE, Pixelar, O3, O4)
2. **Con caras, sin menores**: O3 genera marcos y cierra (no se ejecutan Pixelar ni O4)
3. **Con caras, con menores**: pipeline completo hasta O4

## Contratos de los mensajes (JSON)

Los schemas completos estan en `shared/events/`. A continuacion un resumen de cada uno.

### `images.raw.send`

```json
{
  "GUID_Solicitud": "550e8400-e29b-41d4-a716-446655440000",
  "s3_key": "originales/550e8400-e29b-41d4-a716-446655440000.jpg",
  "timestamp": "2026-04-30T10:00:00Z"
}
```

### `images.faces_detected`

```json
{
  "GUID_Solicitud": "550e8400-e29b-41d4-a716-446655440000",
  "s3_key": "originales/550e8400-e29b-41d4-a716-446655440000.jpg",
  "faces": [
    {
      "id_imagen": 0,
      "bbox": { "x": 120, "y": 50, "w": 80, "h": 100 }
    },
    {
      "id_imagen": 1,
      "bbox": { "x": 300, "y": 60, "w": 75, "h": 95 }
    }
  ]
}
```

### `images.faces_detected.send`

```json
{
  "GUID_Solicitud": "550e8400-e29b-41d4-a716-446655440000",
  "s3_key": "originales/550e8400-e29b-41d4-a716-446655440000.jpg",
  "faces": [
    {
      "id_imagen": 0,
      "bbox": { "x": 120, "y": 50, "w": 80, "h": 100 },
      "url_imagen": "caras/550e8400-e29b-41d4-a716-446655440000/0.jpg"
    }
  ]
}
```

### `images.age_estimated`

```json
{
  "GUID_Solicitud": "550e8400-e29b-41d4-a716-446655440000",
  "s3_key": "originales/550e8400-e29b-41d4-a716-446655440000.jpg",
  "faces": [
    {
      "id_imagen": 0,
      "bbox": { "x": 120, "y": 50, "w": 80, "h": 100 },
      "url_imagen": "caras/550e8400-e29b-41d4-a716-446655440000/0.jpg",
      "score": 0.8723,
      "es_menor": true
    },
    {
      "id_imagen": 1,
      "bbox": { "x": 300, "y": 60, "w": 75, "h": 95 },
      "url_imagen": "caras/550e8400-e29b-41d4-a716-446655440000/1.jpg",
      "score": 0.1204,
      "es_menor": false
    }
  ]
}
```

### `images.age_estimated.send`

Mismo formato que `images.age_estimated`. O3 lo reenvia tal cual cuando hay menores.

### `images.processed`

```json
{
  "GUID_Solicitud": "550e8400-e29b-41d4-a716-446655440000",
  "marcos_key": "marcos/550e8400-e29b-41d4-a716-446655440000.jpg",
  "definitivas_key": "definitivas/550e8400-e29b-41d4-a716-446655440000.jpg",
  "faces": [
    {
      "id_imagen": 0,
      "bbox": { "x": 120, "y": 50, "w": 80, "h": 100 },
      "score": 0.8723,
      "es_menor": true,
      "url_imagen": "caras/550e8400-e29b-41d4-a716-446655440000/0.jpg"
    }
  ]
}
```

## Estados de la solicitud


| Estado             | Quien lo asigna       | Significado                                   |
| ------------------ | --------------------- | --------------------------------------------- |
| `CREADA`           | api_upload (O1)       | Solicitud recibida, imagen en MinIO           |
| `CARAS_DETECTADAS` | O2                    | Deteccion de caras finalizada                 |
| `EDAD_CALCULADA`   | O3                    | Estimacion de edad finalizada                 |
| `COMPLETADA`       | O2, O3 u O4           | Pipeline terminado con exito                  |
| `FALLIDA`          | Cualquier orquestador | Error no recuperable durante el procesamiento |


## Timestamps registrados por fase


| Columna                           | Quien la escribe | Momento                                              |
| --------------------------------- | ---------------- | ---------------------------------------------------- |
| `Inicio_Solicitud`                | api_upload       | Al crear la solicitud                                |
| `Inicio_Deteccion_Caras`          | api_upload       | Justo antes de publicar `images.raw.send`            |
| `Fin_Deteccion_Caras`             | O2               | Al recibir `images.faces_detected`                   |
| `Inicio_Edad`                     | O2               | Justo antes de publicar `images.faces_detected.send` |
| `Fin_edad`                        | O3               | Al recibir `images.age_estimated`                    |
| `Inicio_Pixelado`                 | O3               | Justo antes de publicar `images.age_estimated.send`  |
| `Fin_Pixelado`                    | O4               | Al recibir `images.processed`                        |
| `Inicio_Almacenamiento_Solicitud` | O2, O3 u O4      | Al comenzar la escritura final en BD/MinIO           |
| `Fin_Almacenamiento_Solicitud`    | O2, O3 u O4      | Al terminar la escritura final                       |
| `Fin_Solicitud`                   | O2, O3 u O4      | Al marcar `COMPLETADA`                               |


