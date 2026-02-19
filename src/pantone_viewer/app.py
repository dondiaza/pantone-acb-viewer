from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from .repository import ACBRepository


def create_app(acb_dir: str | Path | None = None) -> Flask:
    project_root = Path(__file__).resolve().parents[2]
    configured_acb_dir = acb_dir or os.getenv("ACB_DIR") or (project_root / "acb")

    app = Flask(
        __name__,
        template_folder=str(project_root / "templates"),
        static_folder=str(project_root / "static"),
    )

    repository = ACBRepository(configured_acb_dir)

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/books")
    def list_books():
        books, error = repository.list_books()
        payload: dict[str, object] = {"books": books}
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
        if not query:
            return jsonify({"error": "Missing query parameter: hex"}), 400

        try:
            payload = repository.search_by_hex(query)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 500
        return jsonify(payload)

    return app
