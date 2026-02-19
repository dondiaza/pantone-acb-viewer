# Pantone ACB Viewer

Visor de bibliotecas Pantone (`.acb`, `.ase`) con analisis de archivos `.psd`, `.png`, `.jpg` y `.jpeg`.

## Funcionalidades clave

- Listado y visualizacion de paletas ACB/ASE.
- Buscador HEX con filtro por paleta.
- Importador multiarchivo por drag & drop.
- Importador por URL de archivo.
- Slider de ruido:
  - bajo = color mas global
  - alto = mas muestras distintas
- Checkbox para incluir capas no visibles.
- Checkbox para incluir superposicion/efectos de color.
- Resultado agrupado por archivo -> por capa -> por color.
- Resumen global por Pantones sugeridos (no por HEX detectado).
- Carga por chunks para evitar errores de payload en produccion.

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
- `GET /api/search?hex=#RRGGBB&book_id=<opcional>`
- `POST /api/import/init`
- `POST /api/import/<upload_id>/chunk`
- `POST /api/import/<upload_id>/finish`
  - campos: `filename`, `book_id`, `noise`, `include_hidden`, `include_overlay`
- `POST /api/import/url`
  - JSON: `url`, `book_id`, `noise`, `include_hidden`, `include_overlay`
- `POST /api/psd/suggest` (compatibilidad subida directa)

## Tests

```powershell
python -m pytest
```

