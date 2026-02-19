"use strict";

document.addEventListener("DOMContentLoaded", () => {
  loadBooks().catch((error) => {
    showMessage(`Unexpected error: ${error.message}`, true);
  });
});

async function loadBooks() {
  showMessage("Loading ACB books...");
  const response = await fetch("/api/books");
  const payload = await response.json();

  const booksRoot = document.getElementById("books");
  booksRoot.innerHTML = "";

  if (payload.error) {
    showMessage(payload.error, true);
  } else {
    clearMessages();
  }

  const books = payload.books || [];
  if (books.length === 0) {
    showMessage("No .acb files found in ./acb/", true);
    return;
  }

  for (const book of books) {
    booksRoot.appendChild(createBookDetails(book));
  }
}

function createBookDetails(book) {
  const details = document.createElement("details");
  details.className = "book";
  details.dataset.bookId = book.id;

  const summary = document.createElement("summary");
  const title = document.createElement("span");
  title.textContent = `${book.title || book.filename}`;
  summary.appendChild(title);

  const meta = document.createElement("span");
  meta.className = "summary-meta";
  if (book.error) {
    meta.innerHTML = `<span class="badge-error">parse error</span>`;
  } else {
    const count = book.color_count ?? "?";
    const space = book.colorspace || "Unknown";
    meta.textContent = `${count} colors · ${space}`;
  }
  summary.appendChild(meta);
  details.appendChild(summary);

  const body = document.createElement("div");
  body.className = "book-body";
  body.hidden = true;
  if (book.error) {
    const error = document.createElement("div");
    error.className = "message error";
    error.textContent = book.error;
    body.hidden = false;
    body.appendChild(error);
  } else {
    body.textContent = "Open to load colors...";
  }
  details.appendChild(body);

  if (!book.error) {
    details.addEventListener("toggle", async () => {
      if (!details.open) {
        return;
      }
      if (details.dataset.loaded === "true") {
        return;
      }

      body.hidden = false;
      body.textContent = "Loading colors...";
      try {
        const loaded = await fetchBook(book.id);
        body.innerHTML = "";
        body.appendChild(renderColorGrid(loaded.colors || []));
        details.dataset.loaded = "true";
      } catch (error) {
        body.innerHTML = "";
        const failure = document.createElement("div");
        failure.className = "message error";
        failure.textContent = `Failed to load ${book.filename}: ${error.message}`;
        body.appendChild(failure);
      }
    });
  }

  return details;
}

async function fetchBook(bookId) {
  const response = await fetch(`/api/books/${encodeURIComponent(bookId)}`);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

function renderColorGrid(colors) {
  const grid = document.createElement("div");
  grid.className = "color-grid";

  if (colors.length === 0) {
    const empty = document.createElement("div");
    empty.className = "message";
    empty.textContent = "No valid colors in this book.";
    grid.appendChild(empty);
    return grid;
  }

  for (const color of colors) {
    const card = document.createElement("article");
    card.className = "card";

    const swatch = document.createElement("div");
    swatch.className = "swatch";
    swatch.style.background = color.hex;
    swatch.title = color.hex;
    card.appendChild(swatch);

    const body = document.createElement("div");
    body.className = "card-body";

    const name = document.createElement("div");
    name.className = "name";
    name.textContent = color.name;
    body.appendChild(name);

    const line = document.createElement("div");
    line.className = "line";
    const hex = document.createElement("span");
    hex.className = "hex";
    hex.textContent = color.hex;
    line.appendChild(hex);

    if (color.code) {
      const code = document.createElement("span");
      code.className = "code";
      code.textContent = color.code;
      line.appendChild(code);
    }

    body.appendChild(line);
    card.appendChild(body);
    grid.appendChild(card);
  }

  return grid;
}

function showMessage(text, isError = false) {
  const root = document.getElementById("messages");
  root.innerHTML = "";

  const message = document.createElement("div");
  message.className = `message${isError ? " error" : ""}`;
  message.textContent = text;
  root.appendChild(message);
}

function clearMessages() {
  const root = document.getElementById("messages");
  root.innerHTML = "";
}

