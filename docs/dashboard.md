# Construcción del Dashboard de Detección de Menores

**Objetivo:** Diseñar y construir un Dashboard en Power BI que permita analizar el rendimiento del pipeline de detección de menores, la calidad del modelo de estimación de edad y el volumen de procesamiento del sistema.

## Páginas del Dashboard

### 1. General

**Descripción**: Estado general del sistema y volumen de procesamiento.

**Métricas (KPIs)**

- **Total Solicitudes**: con total de completadas.
- **% Éxito**: con total de fallidas.
- **Tiempo Medio (s)**: tiempo medio total del pipeline.
- **Total Caras Detectadas**: con media de caras por solicitud.
- **% Menores**: con total de menores detectados.

**Gráficos**

- **Línea**: Solicitudes por día (agrupado por día de la semana).
- **Donut**: Estado de solicitudes (COMPLETADA, FALLIDA, en curso).
- **Barras verticales**: Caras por solicitud (histograma por rango: 0, 1, 2, 3, 4, 5+).
- **Tabla**: Últimas solicitudes.
  - Columnas: Solicitud, Estado, Caras, Tiempo (s).

---

### 2. Pipeline

**Descripción**: Tiempos medios de respuesta por fase del pipeline.

**Métricas (KPIs)**

- **T. Detección caras (s)**: con indicador de fase más rápida.
- **T. Estimación edad (s)**: con % del total.
- **T. Pixelado (s)**: con indicador de fase más lenta.
- **T. Total (s)**: con total de solicitudes procesadas.

**Gráficos**

- **Barras horizontales**: Desglose tiempo medio por fase.
- **Líneas**: Tendencia por día (4 líneas: detección, edad, pixelado, total).
- **Barras apiladas**: Tiempo por fase según nº caras.
- **Tabla**: Solicitudes más lentas.
  - Columnas: Caras, Detección (s), Edad (s), Pixelado (s), Total (s).

---

### 3. Detección

**Descripción**: Calidad y confianza del modelo de detección.

**Métricas (KPIs)**

- **Menores Detectados**: con % del total.
- **% Alta Confianza**: con descripción del umbral (score >0.8 o <0.2).
- **Score Medio (Menores)**: con indicador de alta confianza.
- **Casos Baja Confianza**: con % del total.

**Gráficos**

- **Barras verticales**: Distribución del Score (histograma por rangos de 0.1).
- **Donut**: Proporción de menores y mayores.
- **Box Plot**: Score por clasificación (plugin AppSource: Box and Whisker).
- **Tabla**: Casos de baja confianza (Score 0,40 - 0,60).
  - Columnas: GUID, ID, Score, Clasificación, Tamaño.

---

## Columnas creadas

### Tabla `public solicitud`

- **seg_deteccion**: duración en segundos de la fase de detección de caras.
- **seg_edad**: duración en segundos de la fase de estimación de edad.
- **seg_pixelado**: duración en segundos de la fase de pixelado.
- **seg_total**: duración total en segundos de la solicitud.
- **num_caras**: número de caras detectadas por solicitud.
- **rango_caras**: agrupación del número de caras en rangos (0, 1, 2, 3, 4, 5+).
- **guid_corto**: GUID truncado a 8 caracteres para visualización.
- **seg_deteccion_clean**: duración de detección reemplazando valores vacíos por 0.
- **seg_edad_clean**: duración de edad reemplazando valores vacíos por 0.
- **seg_pixelado_clean**: duración de pixelado reemplazando valores vacíos por 0.

### Tabla `public imagenes`

- **clasificacion**: etiqueta legible ("Mayor de 18" / "Menor de 18").
- **rango_score**: agrupación del score en rangos de 0.1 (0.0-0.1, 0.1-0.2, ..., 0.9-1.0).
- **orden_score**: valor numérico para ordenar correctamente los rangos de score.
- **area_cara**: área de la cara en píxeles cuadrados.
- **tamano_cara**: dimensiones de la cara en formato legible (ej: "64x71 px").
- **guid_corto**: GUID recortado a 8 caracteres.

---

## Medidas creadas

### Tabla `public solicitud`

- **total_solicitudes**
- **pct_exito**
- **tiempo_medio_seg**
- **media_deteccion**
- **media_edad**
- **media_pixelado**
- **media_total**
- **ref_completadas**
- **ref_fallidas**
- **ref_caras_por_solicitud**
- **ref_pct_edad**
- **ref_total_solicitudes**
- **ref_pixelado**
- **ref_deteccion**

### Tabla `public imagenes`

- **total_caras**
- **pct_menores**
- **total_menores**
- **score_medio_menores**
- **pct_alta_confianza**
- **casos_baja_confianza**
- **ref_total_menores**
- **ref_pct_menores**
- **ref_alta_confianza**
- **ref_alta_confianza_label**
- **ref_pct_baja_confianza**
