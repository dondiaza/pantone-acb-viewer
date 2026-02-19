"use strict";

const MAX_PSD_UPLOAD_BYTES = 150 * 1024 * 1024;
const ALLOWED_IMAGE_EXTENSIONS = [".psd", ".png", ".jpg", ".jpeg"];

const state = {
  books: [],
  defaultPaletteId: null,
  psdFile: null,
};

document.addEventListener("DOMContentLoaded", () => {
  setupZoom();
  setupCollapseAll();
  setupHexSearch();
  setupPsdImport();
  loadBooks().catch((error) => {
    showMessage(`Error inesperado: ${error.message}`, true);
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
      const payload = await parseApiResponse(response);
      if (!response.ok) {
        throw new Error(payload.error || `HTTP ${response.status}`);
      }
      renderSearchResults(payload);
    } catch (error) {
      showMessage(`Fallo en la busqueda HEX: ${error.message}`, true);
    }
  });
}

function setupPsdImport() {
  const form = document.getElementById("psdForm");
  const fileInput = document.getElementById("psdFileInput");
  const fileLabel = document.getElementById("psdFileName");
  const dropZone = document.getElementById("psdDropZone");

  const setFile = (file) => {
    if (!file) {
      state.psdFile = null;
      fileLabel.textContent = "Ningun archivo seleccionado";
      return;
    }

    const lowerName = file.name.toLowerCase();
    const valid = ALLOWED_IMAGE_EXTENSIONS.some((ext) => lowerName.endsWith(ext));
    if (!valid) {
      showMessage("Solo se admiten archivos .psd, .png, .jpg o .jpeg.", true);
      return;
    }

    state.psdFile = file;
    fileLabel.textContent = `${file.name} (${prettyBytes(file.size)})`;

    try {
      const dt = new DataTransfer();
      dt.items.add(file);
      fileInput.files = dt.files;
    } catch {
      // Mejor esfuerzo para reflejar el archivo soltado en el input oculto.
    }
  };

  fileInput.addEventListener("change", () => {
    const file = fileInput.files && fileInput.files[0];
    setFile(file || null);
  });

  dropZone.addEventListener("click", () => fileInput.click());
  dropZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fileInput.click();
    }
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("dragover");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.remove("dragover");
    });
  });

  dropZone.addEventListener("drop", (event) => {
    const files = event.dataTransfer?.files;
    if (!files || files.length === 0) {
      return;
    }
    setFile(files[0]);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const paletteSelect = document.getElementById("psdBookSelect");
    const file = state.psdFile;
    if (!file) {
      showMessage("Primero selecciona o arrastra un archivo.", true);
      return;
    }

    try {
      const payload = await uploadAndAnalyzeFile(file, paletteSelect.value || "");
      renderPsdResults(payload);
      clearMessages();
    } catch (error) {
      showMessage(`Fallo en el analisis del archivo: ${error.message}`, true);
    }
  });
}

async function uploadAndAnalyzeFile(file, paletteId) {
  showMessage("Iniciando carga...");
  const initResponse = await fetch("/api/import/init", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name }),
  });
  const initPayload = await parseApiResponse(initResponse);
  if (!initResponse.ok) {
    throw new Error(initPayload.error || `HTTP ${initResponse.status}`);
  }

  const uploadId = initPayload.upload_id;
  const chunkSize = Number(initPayload.chunk_size || 2 * 1024 * 1024);
  const totalChunks = Math.max(1, Math.ceil(file.size / chunkSize));

  for (let index = 0; index < totalChunks; index += 1) {
    const start = index * chunkSize;
    const end = Math.min(file.size, start + chunkSize);
    const chunk = file.slice(start, end);

    const chunkBody = new FormData();
    chunkBody.append("chunk", chunk, `${file.name}.part${index}`);

    const chunkResponse = await fetch(`/api/import/${encodeURIComponent(uploadId)}/chunk`, {
      method: "POST",
      body: chunkBody,
    });
    const chunkPayload = await parseApiResponse(chunkResponse);
    if (!chunkResponse.ok) {
      throw new Error(chunkPayload.error || `HTTP ${chunkResponse.status}`);
    }

    const percent = Math.round(((index + 1) / totalChunks) * 100);
    showMessage(`Subiendo archivo... ${percent}%`);
  }

  showMessage("Procesando colores...");
  const finishBody = new FormData();
  finishBody.append("filename", file.name);
  if (paletteId) {
    finishBody.append("book_id", paletteId);
  }

  const finishResponse = await fetch(`/api/import/${encodeURIComponent(uploadId)}/finish`, {
    method: "POST",
    body: finishBody,
  });
  const finishPayload = await parseApiResponse(finishResponse);
  if (!finishResponse.ok) {
    throw new Error(formatApiError(finishResponse.status, finishPayload.error || ""));
  }
  return finishPayload;
}

async function loadBooks() {
  showMessage("Cargando bibliotecas de muestras...");
  const response = await fetch("/api/books");
  const payload = await parseApiResponse(response);

  const booksRoot = document.getElementById("books");
  booksRoot.innerHTML = "";

  if (payload.error) {
    showMessage(payload.error, true);
  } else {
    clearMessages();
  }

  const books = payload.books || [];
  if (books.length === 0) {
    showMessage("No se encontraron archivos .acb / .ase en ./acb/", true);
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
  allOption.textContent = "Todas las paletas";
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
    meta.innerHTML = `<span class="badge-error">error de parseo</span>`;
  } else {
    const count = book.color_count ?? "?";
    const space = book.colorspace || "Desconocido";
    const format = book.format || "UNK";
    meta.textContent = `${count} colores | ${space} | ${format}`;
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
    body.textContent = "Abre para cargar colores...";
  }
  details.appendChild(body);

  if (!book.error) {
    details.addEventListener("toggle", async () => {
      if (!details.open || details.dataset.loaded === "true") {
        return;
      }

      body.hidden = false;
      body.textContent = "Cargando colores...";
      try {
        const loaded = await fetchBook(book.id);
        body.innerHTML = "";
        body.appendChild(renderColorGrid(loaded.colors || []));
        details.dataset.loaded = "true";
      } catch (error) {
        body.innerHTML = "";
        const failure = document.createElement("div");
        failure.className = "message error";
        failure.textContent = `No se pudo cargar ${book.filename}: ${error.message}`;
        body.appendChild(failure);
      }
    });
  }

  return details;
}

async function fetchBook(bookId) {
  const response = await fetch(`/api/books/${encodeURIComponent(bookId)}`);
  const payload = await parseApiResponse(response);
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
    empty.textContent = "No hay colores validos en esta biblioteca.";
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

  summary.textContent = `${payload.query} | ambito: ${payload.scope} | coincidencias exactas: ${payload.exact_count}`;

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
    empty.textContent = "Sin coincidencias.";
    textList.appendChild(empty);
  }
}

function renderPsdResults(payload) {
  const section = document.getElementById("psdResults");
  const summary = document.getElementById("psdSummary");
  const summaryCardsRoot = document.getElementById("psdSummaryCards");
  const cardsRoot = document.getElementById("psdCards");

  section.hidden = false;
  summaryCardsRoot.innerHTML = "";
  cardsRoot.innerHTML = "";
  summary.textContent = `${payload.filename || "Archivo"} | paleta: ${payload.palette_title} | capas analizadas: ${payload.layer_count}`;

  const summaryColors = payload.summary_colors || [];
  if (summaryColors.length === 0) {
    const emptySummary = document.createElement("div");
    emptySummary.className = "message";
    emptySummary.textContent = "No se detectaron colores.";
    summaryCardsRoot.appendChild(emptySummary);
  } else {
    for (const item of summaryColors) {
      const card = createColorCard({
        name: `${item.pantone.name} · ${item.occurrences} apariciones`,
        code: item.pantone.code,
        hex: item.pantone.hex,
      });
      const info = document.createElement("div");
      info.className = "code";
      info.textContent = `Paleta ${item.pantone.book_title} | Capas: ${item.layers.join(", ")}`;
      card.querySelector(".card-body").appendChild(info);
      summaryCardsRoot.appendChild(card);
    }
  }

  const layers = payload.layers || [];
  if (layers.length === 0) {
    const empty = document.createElement("div");
    empty.className = "message";
    empty.textContent = "No se encontraron capas con color.";
    cardsRoot.appendChild(empty);
    return;
  }

  for (const layer of layers) {
    cardsRoot.appendChild(createLayerColorCard(layer));
  }
}

function createLayerColorCard(layer) {
  const card = document.createElement("article");
  card.className = "psd-card";

  const title = document.createElement("div");
  title.className = "name";
  title.textContent = layer.layer_name;
  card.appendChild(title);

  const grid = document.createElement("div");
  grid.className = "psd-swatches";

  const colors = layer.colors || [];
  colors.forEach((color, index) => {
    const item = document.createElement("div");
    item.className = "psd-swatch-wrap";

    const swatch = document.createElement("div");
    swatch.className = "psd-swatch";
    swatch.style.background = color.pantone.hex;
    swatch.title = `${color.detected_hex} -> ${color.pantone.name} (${color.pantone.hex})`;

    const label = document.createElement("span");
    label.className = "psd-swatch-label";
    label.textContent = `Color ${index + 1}`;

    item.appendChild(swatch);
    item.appendChild(label);
    grid.appendChild(item);
  });
  card.appendChild(grid);

  const meta = document.createElement("div");
  meta.className = "psd-meta";

  colors.forEach((color, index) => {
    const line = document.createElement("div");
    line.innerHTML = `
      <strong>Color ${index + 1}</strong>:
      Detectado <span class="hex">${color.detected_hex}</span> ->
      ${escapeHtml(color.pantone.name)} <span class="hex">${color.pantone.hex}</span>
    `;
    meta.appendChild(line);
  });

  card.appendChild(meta);
  return card;
}

async function parseApiResponse(response) {
  const text = await response.text();
  if (!text) {
    return {};
  }

  try {
    return JSON.parse(text);
  } catch {
    return { error: text };
  }
}

function formatApiError(status, errorText) {
  const clean = (errorText || "").trim();
  const low = clean.toLowerCase();

  if (status === 413 || low.includes("request entity too large")) {
    return `El servidor rechazo la carga por tamano. Limite configurado: ${prettyBytes(MAX_PSD_UPLOAD_BYTES)}.`;
  }

  if (clean.length === 0) {
    return `HTTP ${status}`;
  }

  return clean;
}

function prettyBytes(bytes) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const kb = bytes / 1024;
  if (kb < 1024) {
    return `${kb.toFixed(1)} KB`;
  }
  return `${(kb / 1024).toFixed(1)} MB`;
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
