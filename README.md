# Pantone ACB Viewer (MVP)

Visualizador minimalista de bibliotecas Pantone en archivos `.acb` y `.ase`, solo lectura.

## Requisitos

- Python 3.11+
- Archivos `.acb` y/o `.ase` en `./acb/`

## Estructura

```
.
├─ acb/                     # coloca aqui tus .acb y .ase
├─ app.py
├─ requirements.txt
├─ src/
│  └─ pantone_viewer/
│     ├─ app.py
│     ├─ acb_parser.py
│     ├─ ase_parser.py
│     ├─ color_convert.py
│     └─ repository.py
├─ static/
│  ├─ app.js
│  └─ styles.css
├─ templates/
│  └─ index.html
└─ tests/
   ├─ test_color_convert.py
   └─ test_parser.py
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
  - Respuesta: `{ "books": [{ id, filename, title, format, color_count, colorspace, error? }], "error"?: "..." }`
- `GET /api/books/<id>`
  - Respuesta: `{ id, title, filename, format, colorspace, colors: [{ name, code, hex }] }`
- `GET /api/search?hex=#RRGGBB`
  - Respuesta: `{ query, exact_count, exact_matches: [...], nearest: [...] }`

## Notas de funcionamiento

- Parser ACB implementado sin dependencias externas de ACB.
- Parser ASE implementado sin dependencias externas de ASE.
- Soporta `RGB (0)`, `CMYK (2)` y `Lab (7)` con conversion a HEX `#RRGGBB`.
- Incluye zoom de rejilla para ver mas/menos tarjetas por fila.
- Incluye buscador HEX con resultados en tarjetas y texto.
- Ignora registros dummy (nombre vacio).
- Cache en memoria por libro con invalidacion por `mtime`.
- Si un `.acb` falla al parsear, se reporta en `/api/books` sin romper la app.

## Tests

```powershell
pytest
```
