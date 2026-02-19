from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

from .psd_suggester import suggest_from_psd_bytes
from .repository import ACBRepository


def create_app(acb_dir: str | Path | None = None) -> Flask:
    project_root = Path(__file__).resolve().parents[2]
    configured_acb_dir = acb_dir or os.getenv("ACB_DIR") or (project_root / "acb")

    app = Flask(
        __name__,
        template_folder=str(project_root / "templates"),
        static_folder=str(project_root / "static"),
    )
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

    repository = ACBRepository(configured_acb_dir)

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
            return jsonify({"error": f"Book not found: {book_id}"}), 404
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
            return jsonify({"error": "Missing query parameter: hex"}), 400

        try:
            payload = repository.search_by_hex(query, book_id=book_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except KeyError:
            return jsonify({"error": f"Book not found: {book_id}"}), 404
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 500
        return jsonify(payload)

    @app.post("/api/psd/suggest")
    def suggest_from_psd():
        file = request.files.get("file")
        if file is None:
            return jsonify({"error": "Missing file field: file"}), 400

        file_bytes = file.read()
        if not file_bytes:
            return jsonify({"error": "Uploaded PSD is empty"}), 400

        palette_id = request.form.get("book_id", "").strip() or repository.get_default_palette_id()
        if not palette_id:
            return jsonify({"error": "No palette available"}), 400

        try:
            payload = suggest_from_psd_bytes(file_bytes, repository, palette_id)
            payload["palette_id"] = palette_id
            payload["palette_title"] = repository.get_palette_title(palette_id)
            payload["filename"] = file.filename
        except KeyError:
            return jsonify({"error": f"Book not found: {palette_id}"}), 404
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 422
        except Exception as exc:
            return jsonify({"error": f"Failed to parse PSD: {exc}"}), 422
        return jsonify(payload)

    @app.errorhandler(RequestEntityTooLarge)
    def handle_file_too_large(_exc: RequestEntityTooLarge):
        return jsonify({"error": "Uploaded file is too large for server limits."}), 413

    return app
