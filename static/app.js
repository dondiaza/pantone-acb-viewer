"use strict";

const state = {
  books: [],
  defaultPaletteId: null,
};

document.addEventListener("DOMContentLoaded", () => {
  setupZoom();
  setupCollapseAll();
  setupHexSearch();
  setupPsdImport();
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

function setupCollapseAll() {
  const button = document.getElementById("collapseAllBtn");
  button.addEventListener("click", () => {
    document.querySelectorAll("details.book").forEach((item) => {
      item.open = false;
    });
  });
}

function setupHexSearch() {
  const form = document.getElementById("hexSearchForm");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const input = document.getElementById("hexInput");
    const select = document.getElementById("searchBookSelect");
    const query = input.value.trim();
    if (!query) {
      return;
    }

    const params = new URLSearchParams({ hex: query });
    if (select.value) {
      params.set("book_id", select.value);
    }

    try {
      const response = await fetch(`/api/search?${params.toString()}`);
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

function setupPsdImport() {
  const form = document.getElementById("psdForm");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const fileInput = document.getElementById("psdFileInput");
    const paletteSelect = document.getElementById("psdBookSelect");
    const file = fileInput.files && fileInput.files[0];
    if (!file) {
      showMessage("Select a PSD file first.", true);
      return;
    }

    const body = new FormData();
    body.append("file", file);
    if (paletteSelect.value) {
      body.append("book_id", paletteSelect.value);
    }

    try {
      showMessage("Analyzing PSD layers...");
      const response = await fetch("/api/psd/suggest", { method: "POST", body });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || `HTTP ${response.status}`);
      }
      renderPsdResults(payload);
      clearMessages();
    } catch (error) {
      showMessage(`PSD analysis failed: ${error.message}`, true);
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

  state.books = books.filter((book) => !book.error);
  state.defaultPaletteId = payload.default_palette_id || findDefaultPaletteId(state.books);
  populatePaletteSelectors(state.books, state.defaultPaletteId);

  for (const book of books) {
    booksRoot.appendChild(createBookDetails(book));
  }
}

function findDefaultPaletteId(books) {
  const preferred = books.find(
    (book) => (book.filename || "").toLowerCase() === "pantone solid coated-v4.acb",
  );
  if (preferred) {
    return preferred.id;
  }

  const acbFirst = books.find((book) => (book.format || "").toUpperCase() === "ACB");
  if (acbFirst) {
    return acbFirst.id;
  }

  return books.length > 0 ? books[0].id : "";
}

function populatePaletteSelectors(books, defaultId) {
  const searchSelect = document.getElementById("searchBookSelect");
  const psdSelect = document.getElementById("psdBookSelect");

  searchSelect.innerHTML = "";
  psdSelect.innerHTML = "";

  const allOption = document.createElement("option");
  allOption.value = "";
  allOption.textContent = "All palettes";
  searchSelect.appendChild(allOption);

  for (const book of books) {
    const label = `${book.title} (${book.format})`;
    searchSelect.appendChild(new Option(label, book.id));
    psdSelect.appendChild(new Option(label, book.id));
  }

  if (defaultId) {
    searchSelect.value = defaultId;
    psdSelect.value = defaultId;
  } else {
    searchSelect.value = "";
    psdSelect.value = "";
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

  summary.textContent = `${payload.query} | scope: ${payload.scope} | exact matches: ${payload.exact_count}`;

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
}

function renderPsdResults(payload) {
  const section = document.getElementById("psdResults");
  const summary = document.getElementById("psdSummary");
  const cardsRoot = document.getElementById("psdCards");

  section.hidden = false;
  cardsRoot.innerHTML = "";
  summary.textContent = `${payload.filename || "PSD"} | palette: ${payload.palette_title} | layers analyzed: ${payload.layer_count}`;

  const layers = payload.layers || [];
  if (layers.length === 0) {
    const empty = document.createElement("div");
    empty.className = "message";
    empty.textContent = "No pixel layers found.";
    cardsRoot.appendChild(empty);
    return;
  }

  for (const layer of layers) {
    cardsRoot.appendChild(createPsdCard(layer));
  }
}

function createPsdCard(layer) {
  const card = document.createElement("article");
  card.className = "psd-card";

  const swatches = document.createElement("div");
  swatches.className = "psd-swatches";

  swatches.appendChild(createPsdSwatch("Layer", layer.detected_hex));
  swatches.appendChild(createPsdSwatch("Pantone", layer.pantone.hex));

  const meta = document.createElement("div");
  meta.className = "psd-meta";
  meta.innerHTML = `
    <strong>${escapeHtml(layer.layer_name)}</strong><br />
    Detected: <span class="hex">${layer.detected_hex}</span><br />
    Suggested: <strong>${escapeHtml(layer.pantone.name)}</strong> <span class="hex">${layer.pantone.hex}</span><br />
    Palette: ${escapeHtml(layer.pantone.book_title)}
  `;

  card.appendChild(swatches);
  card.appendChild(meta);
  return card;
}

function createPsdSwatch(label, hex) {
  const wrap = document.createElement("div");
  wrap.className = "psd-swatch-wrap";

  const swatch = document.createElement("div");
  swatch.className = "psd-swatch";
  swatch.style.background = hex;
  swatch.title = hex;

  const text = document.createElement("span");
  text.className = "psd-swatch-label";
  text.textContent = label;

  wrap.appendChild(swatch);
  wrap.appendChild(text);
  return wrap;
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
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

