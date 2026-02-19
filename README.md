# Pantone ACB Viewer

Visualizador minimalista de bibliotecas Pantone en archivos `.acb` y `.ase`, con importador `.psd` para sugerencias de Pantone por capa.

## Requisitos

- Python 3.11+
- Archivos `.acb` y/o `.ase` en `./acb/`

## Estructura

```text
.
|- acb/                     # coloca aqui tus .acb y .ase
|- app.py
|- requirements.txt
|- src/
|  \- pantone_viewer/
|     |- app.py
|     |- acb_parser.py
|     |- ase_parser.py
|     |- psd_suggester.py
|     |- color_convert.py
|     \- repository.py
|- static/
|  |- app.js
|  \- styles.css
|- templates/
|  \- index.html
\- tests/
   |- test_ase_parser.py
   |- test_color_convert.py
   \- test_parser.py
```

## Instalacion y ejecucion (uv)

```powershell
uv venv
.venv\Scripts\activate
uv pip install -r requirements.txt
python app.py
```

## Instalacion y ejecucion (pip)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

App web: `http://127.0.0.1:5000`

## API

- `GET /api/books`
  - Respuesta: `{ "books": [{ id, filename, title, format, color_count, colorspace, error? }], "default_palette_id": "...", "error"?: "..." }`
- `GET /api/books/<id>`
  - Respuesta: `{ id, title, filename, format, colorspace, colors: [{ name, code, hex }] }`
- `GET /api/search?hex=#RRGGBB&book_id=<optional>`
  - Respuesta: `{ query, scope, exact_count, exact_matches: [...], nearest: [...] }`
- `POST /api/psd/suggest` (multipart/form-data)
  - Campos: `file` (PSD), `book_id` (opcional)
  - Respuesta: `{ filename, palette_id, palette_title, layer_count, layers: [{ layer_name, detected_hex, pantone: { name, hex, code, distance, ... } }] }`

## Notas de funcionamiento

- Parser ACB implementado sin dependencias externas de ACB.
- Parser ASE implementado sin dependencias externas de ASE.
- PSD importer usando `psd-tools`.
- Soporta `RGB (0)`, `CMYK (2)` y `Lab (7)` con conversion a HEX `#RRGGBB`.
- Incluye zoom de rejilla y boton `Collapse all`.
- Incluye selector opcional de paleta para buscar por HEX. Por defecto usa `PANTONE Solid Coated-V4`.
- En PSD, si no hay match exacto, devuelve el Pantone mas cercano.
- En PSD puedes arrastrar y soltar (`drag & drop`) o seleccionar archivo.
- Limite configurado para subida PSD: 150 MB.
- Cache en memoria por libro con invalidacion por `mtime`.
- Si un archivo falla al parsear, se reporta en `/api/books` sin romper la app.

## Tests

```powershell
python -m pytest
```
