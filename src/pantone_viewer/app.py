from __future__ import annotations

import ipaddress
import os
import socket
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

from .psd_suggester import suggest_from_file_bytes
from .repository import ACBRepository
from .upload_store import UploadStore


def create_app(acb_dir: str | Path | None = None) -> Flask:
    project_root = Path(__file__).resolve().parents[2]
    configured_acb_dir = acb_dir or os.getenv("ACB_DIR") or (project_root / "acb")

    app = Flask(
        __name__,
        template_folder=str(project_root / "templates"),
        static_folder=str(project_root / "static"),
    )
    app.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024

    repository = ACBRepository(configured_acb_dir)
    upload_store = UploadStore()
    jobs: dict[str, dict[str, object]] = {}
    url_cache: dict[str, dict[str, object]] = {}

    @app.before_request
    def bind_trace_id() -> None:
        g.trace_id = uuid.uuid4().hex

    def json_response(payload: dict[str, object], status: int = 200):
        out = dict(payload)
        out["trace_id"] = str(getattr(g, "trace_id", ""))
        response = jsonify(out)
        response.status_code = status
        response.headers["X-Trace-Id"] = out["trace_id"]
        return response

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/health")
    @app.get("/api/v1/health")
    def health():
        return json_response(
            {
                "status": "ok",
                "service": "pantone-viewer",
                "book_cache_dir": str(repository.cache_dir),
            }
        )

    @app.get("/api/books")
    @app.get("/api/v1/books")
    def list_books():
        mode = _parse_mode(request.args.get("mode"))
        books, error = repository.list_books(mode=mode)
        payload: dict[str, object] = {
            "books": books,
            "default_palette_id": repository.get_default_palette_id(),
            "mode": mode,
        }
        if error:
            payload["error"] = error
        return json_response(payload)

    @app.get("/api/books/<book_id>")
    @app.get("/api/v1/books/<book_id>")
    def get_book(book_id: str):
        mode = _parse_mode(request.args.get("mode"))
        try:
            book = repository.get_book_details(book_id, mode=mode)
        except KeyError:
            return json_response({"error": f"Paleta no encontrada: {book_id}"}, 404)
        except FileNotFoundError as exc:
            return json_response({"error": str(exc)}, 500)
        except RuntimeError as exc:
            return json_response({"error": str(exc)}, 422)
        return json_response(book)

    @app.get("/api/books/<book_id>/search")
    @app.get("/api/v1/books/<book_id>/search")
    def search_book_text(book_id: str):
        mode = _parse_mode(request.args.get("mode"))
        query = request.args.get("q", "")
        offset = _parse_int(request.args.get("offset"), 0)
        limit = _parse_int(request.args.get("limit"), 100)
        try:
            payload = repository.search_book_text(
                book_id=book_id,
                query=query,
                offset=offset,
                limit=limit,
                mode=mode,
            )
        except KeyError:
            return json_response({"error": f"Paleta no encontrada: {book_id}"}, 404)
        except FileNotFoundError as exc:
            return json_response({"error": str(exc)}, 500)
        except RuntimeError as exc:
            return json_response({"error": str(exc)}, 422)
        return json_response(payload)

    @app.get("/api/search")
    @app.get("/api/v1/search")
    def search_by_hex():
        query = request.args.get("hex", "") or request.args.get("q", "")
        book_id = request.args.get("book_id", "").strip() or None
        mode = _parse_mode(request.args.get("mode"))
        achromatic_enabled = _parse_bool(request.args.get("achromatic_enabled"), default=True)
        achromatic_threshold_white = _parse_float(
            request.args.get("achromatic_threshold_white"), default=2.0, min_value=0.0, max_value=10.0
        )
        achromatic_threshold_black = _parse_float(
            request.args.get("achromatic_threshold_black"), default=2.0, min_value=0.0, max_value=10.0
        )
        if not query:
            return json_response({"error": "Falta el parametro de consulta: hex/q"}, 400)

        try:
            payload = repository.search_by_hex(
                query,
                book_id=book_id,
                mode=mode,
                achromatic_enabled=achromatic_enabled,
                achromatic_threshold_white=achromatic_threshold_white,
                achromatic_threshold_black=achromatic_threshold_black,
            )
            payload["mode"] = mode
        except ValueError as exc:
            return json_response({"error": str(exc)}, 400)
        except KeyError:
            return json_response({"error": f"Paleta no encontrada: {book_id}"}, 404)
        except FileNotFoundError as exc:
            return json_response({"error": str(exc)}, 500)
        return json_response(payload)

    @app.post("/api/import/init")
    @app.post("/api/v1/import/init")
    def import_init():
        raw = request.get_json(silent=True) or {}
        filename = str(raw.get("filename", "archivo"))
        session = upload_store.create_session(filename=filename)
        jobs[session.upload_id] = {
            "job_id": session.upload_id,
            "status": "uploading",
            "filename": session.filename,
            "uploaded_bytes": 0,
        }
        return json_response(
            {
                "upload_id": session.upload_id,
                "chunk_size": 2 * 1024 * 1024,
                "filename": session.filename,
                "job_id": session.upload_id,
            }
        )

    @app.post("/api/import/<upload_id>/chunk")
    @app.post("/api/v1/import/<upload_id>/chunk")
    def import_chunk(upload_id: str):
        chunk = request.files.get("chunk")
        if chunk is None:
            return json_response({"error": "Falta el campo de archivo: chunk"}, 400)

        chunk_bytes = chunk.read()
        try:
            session = upload_store.append_chunk(upload_id, chunk_bytes)
        except KeyError:
            return json_response({"error": f"Sesion de carga no encontrada: {upload_id}"}, 404)

        jobs.setdefault(upload_id, {"job_id": upload_id, "status": "uploading"})
        jobs[upload_id]["uploaded_bytes"] = session.size
        jobs[upload_id]["status"] = "uploading"
        return json_response({"upload_id": upload_id, "uploaded_bytes": session.size, "job_id": upload_id})

    @app.get("/api/jobs/<job_id>")
    @app.get("/api/v1/jobs/<job_id>")
    def get_job(job_id: str):
        job = jobs.get(job_id)
        if not job:
            return json_response({"error": f"Trabajo no encontrado: {job_id}"}, 404)
        return json_response({"job": job})

    @app.post("/api/import/<upload_id>/finish")
    @app.post("/api/v1/import/<upload_id>/finish")
    def import_finish(upload_id: str):
        mode = _parse_mode(request.form.get("mode"))
        palette_id = request.form.get("book_id", "").strip() or repository.get_default_palette_id()
        if not palette_id:
            return json_response({"error": "No hay paletas disponibles"}, 400)

        noise = _parse_noise(request.form.get("noise"))
        max_colors = _parse_max_colors(request.form.get("max_colors"))
        include_hidden = _parse_bool(request.form.get("include_hidden"))
        include_overlay = _parse_bool(request.form.get("include_overlay"), default=True)
        ignore_background = _parse_bool(request.form.get("ignore_background"))

        try:
            session, file_bytes = upload_store.finalize(upload_id)
        except KeyError:
            return json_response({"error": f"Sesion de carga no encontrada: {upload_id}"}, 404)

        if not file_bytes:
            return json_response({"error": "El archivo subido esta vacio"}, 400)

        filename = request.form.get("filename", "").strip() or session.filename
        jobs[upload_id] = {
            "job_id": upload_id,
            "status": "processing",
            "filename": filename,
            "uploaded_bytes": len(file_bytes),
            "mode": mode,
        }
        try:
            payload = suggest_from_file_bytes(
                file_bytes=file_bytes,
                filename=filename,
                repository=repository,
                palette_id=palette_id,
                mode=mode,
                noise=noise,
                max_colors=max_colors,
                include_hidden=include_hidden,
                include_overlay=include_overlay,
                ignore_background=ignore_background,
            )
            payload["palette_id"] = palette_id
            payload["palette_title"] = repository.get_palette_title(palette_id)
            payload["filename"] = filename
            payload["mode"] = mode
            jobs[upload_id]["status"] = "completed"
        except KeyError:
            jobs[upload_id]["status"] = "failed"
            return json_response({"error": f"Paleta no encontrada: {palette_id}"}, 404)
        except RuntimeError as exc:
            jobs[upload_id]["status"] = "failed"
            return json_response({"error": str(exc)}, 422)
        except Exception as exc:
            jobs[upload_id]["status"] = "failed"
            return json_response({"error": f"No se pudo procesar el archivo: {exc}"}, 422)
        return json_response(payload)

    @app.post("/api/psd/suggest")
    @app.post("/api/v1/psd/suggest")
    def suggest_from_upload_direct():
        mode = _parse_mode(request.form.get("mode"))
        file = request.files.get("file")
        if file is None:
            return json_response({"error": "Falta el campo de archivo: file"}, 400)

        file_bytes = file.read()
        if not file_bytes:
            return json_response({"error": "El archivo subido esta vacio"}, 400)

        palette_id = request.form.get("book_id", "").strip() or repository.get_default_palette_id()
        if not palette_id:
            return json_response({"error": "No hay paletas disponibles"}, 400)

        noise = _parse_noise(request.form.get("noise"))
        max_colors = _parse_max_colors(request.form.get("max_colors"))
        include_hidden = _parse_bool(request.form.get("include_hidden"))
        include_overlay = _parse_bool(request.form.get("include_overlay"), default=True)
        ignore_background = _parse_bool(request.form.get("ignore_background"))

        try:
            payload = suggest_from_file_bytes(
                file_bytes=file_bytes,
                filename=file.filename or "archivo",
                repository=repository,
                palette_id=palette_id,
                mode=mode,
                noise=noise,
                max_colors=max_colors,
                include_hidden=include_hidden,
                include_overlay=include_overlay,
                ignore_background=ignore_background,
            )
            payload["palette_id"] = palette_id
            payload["palette_title"] = repository.get_palette_title(palette_id)
            payload["filename"] = file.filename
            payload["mode"] = mode
        except KeyError:
            return json_response({"error": f"Paleta no encontrada: {palette_id}"}, 404)
        except RuntimeError as exc:
            return json_response({"error": str(exc)}, 422)
        except Exception as exc:
            return json_response({"error": f"No se pudo procesar el archivo: {exc}"}, 422)
        return json_response(payload)

    @app.post("/api/import/url")
    @app.post("/api/v1/import/url")
    def import_from_url():
        raw = request.get_json(silent=True) or {}
        mode = _parse_mode(raw.get("mode"))
        source_url = str(raw.get("url", "")).strip()
        if not source_url:
            return json_response({"error": "Falta la URL de origen"}, 400)

        if not _is_url_allowed(source_url):
            return json_response({"error": "URL no permitida"}, 400)

        palette_id = str(raw.get("book_id", "")).strip() or repository.get_default_palette_id()
        if not palette_id:
            return json_response({"error": "No hay paletas disponibles"}, 400)

        noise = _parse_noise(raw.get("noise"))
        max_colors = _parse_max_colors(raw.get("max_colors"))
        include_hidden = _parse_bool(raw.get("include_hidden"))
        include_overlay = _parse_bool(raw.get("include_overlay"), default=True)
        ignore_background = _parse_bool(raw.get("ignore_background"))

        try:
            cache_item = url_cache.get(source_url)
            if cache_item is not None:
                file_bytes = bytes(cache_item["bytes"])
                content_type = str(cache_item.get("content_type", ""))
            else:
                head_req = urllib.request.Request(
                    source_url,
                    headers={"User-Agent": "PantoneViewer/1.0"},
                    method="HEAD",
                )
                try:
                    with urllib.request.urlopen(head_req, timeout=15) as head_response:
                        content_length = int(head_response.headers.get("Content-Length", "0") or 0)
                        if content_length > (150 * 1024 * 1024):
                            return json_response({"error": "URL supera el limite permitido de tamano."}, 413)
                except Exception:
                    pass

                request_obj = urllib.request.Request(
                    source_url,
                    headers={"User-Agent": "PantoneViewer/1.0"},
                    method="GET",
                )
                with urllib.request.urlopen(request_obj, timeout=45) as response:
                    file_bytes = response.read()
                    content_type = response.headers.get("Content-Type", "")
                    if len(file_bytes) > (150 * 1024 * 1024):
                        return json_response({"error": "URL supera el limite permitido de tamano."}, 413)
                url_cache[source_url] = {"bytes": file_bytes, "content_type": content_type}
        except Exception as exc:
            return json_response({"error": f"No se pudo descargar la URL: {exc}"}, 422)

        if not file_bytes:
            return json_response({"error": "El archivo descargado esta vacio"}, 422)

        filename = _filename_from_url(source_url, content_type)
        try:
            payload = suggest_from_file_bytes(
                file_bytes=file_bytes,
                filename=filename,
                repository=repository,
                palette_id=palette_id,
                mode=mode,
                noise=noise,
                max_colors=max_colors,
                include_hidden=include_hidden,
                include_overlay=include_overlay,
                ignore_background=ignore_background,
            )
            payload["palette_id"] = palette_id
            payload["palette_title"] = repository.get_palette_title(palette_id)
            payload["filename"] = filename
            payload["source_url"] = source_url
            payload["mode"] = mode
        except KeyError:
            return json_response({"error": f"Paleta no encontrada: {palette_id}"}, 404)
        except RuntimeError as exc:
            return json_response({"error": str(exc)}, 422)
        except Exception as exc:
            return json_response({"error": f"No se pudo procesar el archivo descargado: {exc}"}, 422)
        return json_response(payload)

    @app.post("/api/analyze")
    @app.post("/api/v1/analyze")
    def analyze_unified():
        if request.content_type and "application/json" in request.content_type.lower():
            return import_from_url()
        return suggest_from_upload_direct()

    @app.errorhandler(RequestEntityTooLarge)
    def handle_file_too_large(_exc: RequestEntityTooLarge):
        return json_response(
            {
                "error": "El archivo subido supera el limite permitido por el servidor.",
                "error_code": "REQUEST_ENTITY_TOO_LARGE",
            },
            413,
        )

    return app


def _parse_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "si", "sí"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_noise(value) -> float:
    try:
        return max(0.0, min(100.0, float(value)))
    except Exception:
        return 35.0


def _parse_max_colors(value) -> int:
    try:
        return max(0, min(15, int(float(value))))
    except Exception:
        return 0


def _parse_mode(value) -> str:
    text = str(value or "").strip().lower()
    if text == "expert":
        return "expert"
    return "normal"


def _parse_int(value, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _parse_float(value, default: float, min_value: float, max_value: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    return max(min_value, min(max_value, parsed))


def _is_url_allowed(value: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(value)
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.hostname:
        return False

    host = parsed.hostname.lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False
    allow_list_text = str(os.getenv("ALLOWED_URL_DOMAINS", "") or "").strip()
    if allow_list_text:
        allow_list = [item.strip().lower() for item in allow_list_text.split(",") if item.strip()]
        if allow_list and host not in allow_list:
            return False

    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return False
    except ValueError:
        try:
            resolved = socket.gethostbyname(host)
            ip = ipaddress.ip_address(resolved)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return False
        except Exception:
            return False
    return True


def _filename_from_url(url: str, content_type: str) -> str:
    path = urllib.parse.urlparse(url).path
    name = Path(path).name
    if name:
        return name

    if "png" in content_type.lower():
        return "archivo.png"
    if "jpeg" in content_type.lower() or "jpg" in content_type.lower():
        return "archivo.jpg"
    if "photoshop" in content_type.lower() or "psd" in content_type.lower():
        return "archivo.psd"
    return "archivo.bin"

