# Pantone ACB Viewer

Visor de bibliotecas Pantone (`.acb`, `.ase`) con analisis de archivos `.psd`, `.png`, `.jpg` y `.jpeg`.

## Funcionalidades clave

- Selector de modo:
  - `Normal`: flujo actual simplificado.
  - `Experto`: ranking por `ΔE2000`, fiabilidad, metadatos extendidos, buscador avanzado y comparativas.
- Listado y visualizacion de paletas ACB/ASE.
- Buscador HEX con filtro por paleta.
- Buscador experto admite `HEX`, `rgb(...)`, `hsl(...)`, `cmyk(...)` y lectura desde portapapeles.
- Importador multiarchivo por drag & drop.
- Importador por URL de archivo.
- Slider de ruido:
  - bajo = color mas global
  - alto = mas muestras distintas
- Slider de maximo de colores Pantone sugeridos (0-15):
  - 0 = automatico segun ruido
  - 1..15 = limite maximo aplicado al analisis
- Checkbox para incluir capas no visibles.
- Checkbox para incluir superposicion/efectos de color.
- Checkbox para ignorar color de fondo (capas solidas completas).
- Resultado agrupado por archivo -> por capa -> por color.
- Resumen global por Pantones sugeridos (no por HEX detectado).
- Preview en miniatura por capa.
- Carga por chunks para evitar errores de payload en produccion.
- En modo experto:
  - resultado con `ΔE2000` + etiqueta de fiabilidad (`Excelente/Bueno/Dudoso`)
  - comparativa detectado vs sugerido
  - resumen multiarchivo (repetidos y exclusivos)
  - familias de duplicados por cercania colorimetrica
  - cache persistente por libro en `./.cache/*.json` con `mtime + size + hash parcial`
  - metadatos por color: `rgb`, `lab_d50`, `lab_d65`, `cmyk_approx`
- Regla fija de blanco/negro:
  - `#FFFFFF` devuelve siempre `BLANCO`
  - `#000000` devuelve siempre `NEGRO`
  - (experto) casi blanco/negro configurable por umbral

## Requisitos

- Python 3.11+
- Archivos `.acb` y/o `.ase` en `./acb/`

## Ejecutar (uv)

```powershell
uv venv
.venv\Scripts\activate
uv pip install -r requirements.txt
python app.py
```

## Ejecutar (pip)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Web: `http://127.0.0.1:5000`

## API principal

- `GET /api/books`
- `GET /api/books/<id>`
- `GET /api/books/<id>/search?q=<texto>&offset=0&limit=100`
- `GET /api/search?hex=<color>&book_id=<opcional>&mode=<normal|expert>`
  - `color` acepta HEX/rgb/hsl/cmyk
- `POST /api/import/init`
- `POST /api/import/<upload_id>/chunk`
- `POST /api/import/<upload_id>/finish`
  - campos: `filename`, `book_id`, `mode`, `noise`, `max_colors`, `include_hidden`, `include_overlay`, `ignore_background`
- `POST /api/import/url`
  - JSON: `url`, `book_id`, `mode`, `noise`, `max_colors`, `include_hidden`, `include_overlay`, `ignore_background`
- `POST /api/psd/suggest` (compatibilidad subida directa)
- `POST /api/analyze` (unifica archivo/url)
- `GET /api/health`
- `GET /api/jobs/<id>`
- alias versionados en `/api/v1/...`

Todas las respuestas API incluyen `trace_id`.

## Tests

```powershell
python -m pytest
```
