# Pantone ACB Viewer

Visualizador de bibliotecas Pantone (`.acb` y `.ase`) con importador de `.psd`, `.png`, `.jpg` y `.jpeg` para sugerencias de Pantone.

## Requisitos

- Python 3.11+
- Archivos `.acb` y/o `.ase` en `./acb/`

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
- `GET /api/books/<id>`
- `GET /api/search?hex=#RRGGBB&book_id=<opcional>`
- `POST /api/import/init`
  - Devuelve `upload_id` y `chunk_size` para carga en partes.
- `POST /api/import/<upload_id>/chunk` (multipart, campo `chunk`)
- `POST /api/import/<upload_id>/finish` (multipart, `filename`, `book_id` opcional)
  - Devuelve:
    - colores detectados por capa
    - sugerencia Pantone por color
    - resumen global de Pantones sugeridos
- `POST /api/psd/suggest` (compatibilidad, subida directa)

## Notas

- Soporta RGB/CMYK/Lab y conversion a HEX.
- Buscador HEX con alcance por paleta.
- Importador con drag & drop para PSD/JPG/PNG.
- Carga de archivo por chunks para evitar limites de payload en produccion.
- Limite objetivo configurado: 150 MB.
- Cache en memoria por `mtime`.

## Tests

```powershell
python -m pytest
```

