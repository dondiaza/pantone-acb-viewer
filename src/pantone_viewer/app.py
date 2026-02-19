from __future__ import annotations

import os
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

        try:
            payload = suggest_from_file_bytes(
                file_bytes=file_bytes,
                filename=file.filename or "archivo",
                repository=repository,
                palette_id=palette_id,
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

    @app.errorhandler(RequestEntityTooLarge)
    def handle_file_too_large(_exc: RequestEntityTooLarge):
        return jsonify({"error": "El archivo subido supera el limite permitido por el servidor."}), 413

    return app

