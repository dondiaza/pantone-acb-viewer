"use strict";

document.addEventListener("DOMContentLoaded", () => {
  setupZoom();
  setupHexSearch();
  loadBooks().catch((error) => {
    showMessage(`Unexpected error: ${error.message}`, true);
  });
});

function setupZoom() {
  const zoomRange = document.getElementById("zoomRange");
  const zoomLabel = document.getElementById("zoomLabel");

  const applyZoom = () => {
    const value = Number(zoomRange.value);
    document.documentElement.style.setProperty("--card-min", `${value}px`);
    zoomLabel.textContent = `${value}px`;
  };

  zoomRange.addEventListener("input", applyZoom);
  applyZoom();
}

function setupHexSearch() {
  const form = document.getElementById("hexSearchForm");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const input = document.getElementById("hexInput");
    const query = input.value.trim();
    if (!query) {
      return;
    }

    try {
      const response = await fetch(`/api/search?hex=${encodeURIComponent(query)}`);
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || `HTTP ${response.status}`);
      }
      renderSearchResults(payload);
    } catch (error) {
      showMessage(`HEX search failed: ${error.message}`, true);
    }
  });
}

async function loadBooks() {
  showMessage("Loading swatch books...");
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
    showMessage("No .acb / .ase files found in ./acb/", true);
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
    const format = book.format || "UNK";
    meta.textContent = `${count} colors | ${space} | ${format}`;
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
      if (!details.open || details.dataset.loaded === "true") {
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
    grid.appendChild(createColorCard(color));
  }

  return grid;
}

function createColorCard(color) {
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
  return card;
}

function renderSearchResults(payload) {
  const section = document.getElementById("searchResults");
  const summary = document.getElementById("searchSummary");
  const cardsRoot = document.getElementById("searchCards");
  const textList = document.getElementById("searchTextList");

  section.hidden = false;
  cardsRoot.innerHTML = "";
  textList.innerHTML = "";

  const exact = payload.exact_matches || [];
  const nearest = payload.nearest || [];

  summary.textContent = `${payload.query} | exact matches: ${payload.exact_count}`;

  const cardSource = exact.length > 0 ? exact : nearest.slice(0, 48);
  for (const item of cardSource) {
    const card = createColorCard(item);
    const meta = document.createElement("div");
    meta.className = "code";
    meta.textContent = item.book_title;
    card.querySelector(".card-body").appendChild(meta);
    cardsRoot.appendChild(card);
  }

  const textSource = exact.length > 0 ? exact : nearest.slice(0, 150);
  for (const item of textSource) {
    const line = document.createElement("div");
    line.className = "search-line";

    const name = document.createElement("strong");
    name.textContent = item.name;
    line.appendChild(name);

    const hex = document.createElement("span");
    hex.className = "hex";
    hex.textContent = ` ${item.hex} `;
    line.appendChild(hex);

    const path = document.createElement("span");
    path.className = "path";
    path.textContent = `(${item.book_title})`;
    line.appendChild(path);

    textList.appendChild(line);
  }

  if (textSource.length === 0) {
    const empty = document.createElement("div");
    empty.className = "message";
    empty.textContent = "No matches.";
    textList.appendChild(empty);
  }

  clearMessages();
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
