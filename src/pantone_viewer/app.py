from __future__ import annotations

import ipaddress
import os
import socket
import urllib.parse
import urllib.request
from pathlib import Path

from flask import Flask, jsonify, render_template, request
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

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/books")
    def list_books():
        books, error = repository.list_books()
        payload: dict[str, object] = {
            "books": books,
            "default_palette_id": repository.get_default_palette_id(),
        }
        if error:
            payload["error"] = error
        return jsonify(payload)

    @app.get("/api/books/<book_id>")
    def get_book(book_id: str):
        try:
            book = repository.get_book_details(book_id)
        except KeyError:
            return jsonify({"error": f"Paleta no encontrada: {book_id}"}), 404
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 500
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 422
        return jsonify(book)

    @app.get("/api/search")
    def search_by_hex():
        query = request.args.get("hex", "")
        book_id = request.args.get("book_id", "").strip() or None
        if not query:
            return jsonify({"error": "Falta el parametro de consulta: hex"}), 400

        try:
            payload = repository.search_by_hex(query, book_id=book_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except KeyError:
            return jsonify({"error": f"Paleta no encontrada: {book_id}"}), 404
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 500
        return jsonify(payload)

    @app.post("/api/import/init")
    def import_init():
        raw = request.get_json(silent=True) or {}
        filename = str(raw.get("filename", "archivo"))
        session = upload_store.create_session(filename=filename)
        return jsonify(
            {
                "upload_id": session.upload_id,
                "chunk_size": 2 * 1024 * 1024,
                "filename": session.filename,
            }
        )

    @app.post("/api/import/<upload_id>/chunk")
    def import_chunk(upload_id: str):
        chunk = request.files.get("chunk")
        if chunk is None:
            return jsonify({"error": "Falta el campo de archivo: chunk"}), 400

        chunk_bytes = chunk.read()
        try:
            session = upload_store.append_chunk(upload_id, chunk_bytes)
        except KeyError:
            return jsonify({"error": f"Sesion de carga no encontrada: {upload_id}"}), 404

        return jsonify({"upload_id": upload_id, "uploaded_bytes": session.size})

    @app.post("/api/import/<upload_id>/finish")
    def import_finish(upload_id: str):
        palette_id = request.form.get("book_id", "").strip() or repository.get_default_palette_id()
        if not palette_id:
            return jsonify({"error": "No hay paletas disponibles"}), 400

        noise = _parse_noise(request.form.get("noise"))
        include_hidden = _parse_bool(request.form.get("include_hidden"))
        include_overlay = _parse_bool(request.form.get("include_overlay"), default=True)

        try:
            session, file_bytes = upload_store.finalize(upload_id)
        except KeyError:
            return jsonify({"error": f"Sesion de carga no encontrada: {upload_id}"}), 404

        if not file_bytes:
            return jsonify({"error": "El archivo subido esta vacio"}), 400

        filename = request.form.get("filename", "").strip() or session.filename
        try:
            payload = suggest_from_file_bytes(
                file_bytes=file_bytes,
                filename=filename,
                repository=repository,
                palette_id=palette_id,
                noise=noise,
                include_hidden=include_hidden,
                include_overlay=include_overlay,
            )
            payload["palette_id"] = palette_id
            payload["palette_title"] = repository.get_palette_title(palette_id)
            payload["filename"] = filename
        except KeyError:
            return jsonify({"error": f"Paleta no encontrada: {palette_id}"}), 404
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 422
        except Exception as exc:
            return jsonify({"error": f"No se pudo procesar el archivo: {exc}"}), 422
        return jsonify(payload)

    @app.post("/api/psd/suggest")
    def suggest_from_upload_direct():
        file = request.files.get("file")
        if file is None:
            return jsonify({"error": "Falta el campo de archivo: file"}), 400

        file_bytes = file.read()
        if not file_bytes:
            return jsonify({"error": "El archivo subido esta vacio"}), 400

        palette_id = request.form.get("book_id", "").strip() or repository.get_default_palette_id()
        if not palette_id:
            return jsonify({"error": "No hay paletas disponibles"}), 400

        noise = _parse_noise(request.form.get("noise"))
        include_hidden = _parse_bool(request.form.get("include_hidden"))
        include_overlay = _parse_bool(request.form.get("include_overlay"), default=True)

        try:
            payload = suggest_from_file_bytes(
                file_bytes=file_bytes,
                filename=file.filename or "archivo",
                repository=repository,
                palette_id=palette_id,
                noise=noise,
                include_hidden=include_hidden,
                include_overlay=include_overlay,
            )
            payload["palette_id"] = palette_id
            payload["palette_title"] = repository.get_palette_title(palette_id)
            payload["filename"] = file.filename
        except KeyError:
            return jsonify({"error": f"Paleta no encontrada: {palette_id}"}), 404
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 422
        except Exception as exc:
            return jsonify({"error": f"No se pudo procesar el archivo: {exc}"}), 422
        return jsonify(payload)

    @app.post("/api/import/url")
    def import_from_url():
        raw = request.get_json(silent=True) or {}
        source_url = str(raw.get("url", "")).strip()
        if not source_url:
            return jsonify({"error": "Falta la URL de origen"}), 400

        if not _is_url_allowed(source_url):
            return jsonify({"error": "URL no permitida"}), 400

        palette_id = str(raw.get("book_id", "")).strip() or repository.get_default_palette_id()
        if not palette_id:
            return jsonify({"error": "No hay paletas disponibles"}), 400

        noise = _parse_noise(raw.get("noise"))
        include_hidden = _parse_bool(raw.get("include_hidden"))
        include_overlay = _parse_bool(raw.get("include_overlay"), default=True)

        try:
            request_obj = urllib.request.Request(
                source_url,
                headers={"User-Agent": "PantoneViewer/1.0"},
                method="GET",
            )
            with urllib.request.urlopen(request_obj, timeout=45) as response:
                file_bytes = response.read()
                content_type = response.headers.get("Content-Type", "")
        except Exception as exc:
            return jsonify({"error": f"No se pudo descargar la URL: {exc}"}), 422

        if not file_bytes:
            return jsonify({"error": "El archivo descargado esta vacio"}), 422

        filename = _filename_from_url(source_url, content_type)
        try:
            payload = suggest_from_file_bytes(
                file_bytes=file_bytes,
                filename=filename,
                repository=repository,
                palette_id=palette_id,
                noise=noise,
                include_hidden=include_hidden,
                include_overlay=include_overlay,
            )
            payload["palette_id"] = palette_id
            payload["palette_title"] = repository.get_palette_title(palette_id)
            payload["filename"] = filename
            payload["source_url"] = source_url
        except KeyError:
            return jsonify({"error": f"Paleta no encontrada: {palette_id}"}), 404
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 422
        except Exception as exc:
            return jsonify({"error": f"No se pudo procesar el archivo descargado: {exc}"}), 422
        return jsonify(payload)

    @app.errorhandler(RequestEntityTooLarge)
    def handle_file_too_large(_exc: RequestEntityTooLarge):
        return jsonify({"error": "El archivo subido supera el limite permitido por el servidor."}), 413

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
