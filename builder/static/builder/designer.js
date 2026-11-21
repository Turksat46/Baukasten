// Seiten-Designer: Bausteine per Drag-and-drop anordnen und einstellen.
// Der Zustand ist die Liste "layout"; gespeichert wird sie als JSON.
// Die Arbeitsfläche zeigt jeden Baustein so, wie der Server ihn rendert (Vorschau-Adresse).
(function () {
  "use strict";

  var cfg = JSON.parse(document.getElementById("designer-config").textContent);
  var root = document.getElementById("designer");
  var canvas = document.getElementById("canvas");
  var palette = document.getElementById("palette");
  var search = document.getElementById("palette-search");
  var propsEl = document.getElementById("props");
  var statusEl = document.getElementById("status");
  var titleEl = document.getElementById("page-title");
  var navEl = document.getElementById("page-nav");
  var publicEl = document.getElementById("page-public");
  var publicNote = document.getElementById("public-note");
  var conflictNote = document.getElementById("conflict-note");
  var conflictText = conflictNote ? conflictNote.querySelector("[data-conflict-text]") : null;
  var conflictReload = document.getElementById("conflict-reload");

  // Symbole der Bausteine (Linienzeichnungen, 24er Raster)
  var ICONS = {
    heading: "M5 6v12M12 6v12M5 12h7M16 11l3-2v9",
    text: "M5 7h14M5 12h14M5 17h9",
    notice: "M12 3a9 9 0 100 18 9 9 0 000-18zM12 11v6M12 7.4v.2",
    image: "M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M15.5 9.5h.01",
    greeting: "M12 12a4 4 0 100-8 4 4 0 000 8zM4 20c1.5-4 5-5 8-5s6.5 1 8 5",
    table: "M4 5h16v14H4zM4 10h16M4 15h16M10 5v14",
    cards: "M4 5h7v6H4zM13 5h7v6h-7zM4 13h7v6H4zM13 13h7v6h-7z",
    form: "M5 4h14v5H5zM5 12h14v5H5zM5 20h6",
    export: "M12 4v11M8 11l4 4 4-4M5 19h14",
    stat: "M9 4L7 20M17 4l-2 16M4 9h16M3 15h16",
    progress: "M3 9h18v6H3zM3 12h10",
    chart: "M4 4v16M4 7h12M4 12h8M4 17h14",
    donut: "M12 3a9 9 0 109 9h-9zM15 3.5V9h5.5A6.5 6.5 0 0015 3.5z",
    timeline: "M4 20h16M7 20v-6M12 20V7M17 20v-10",
    button: "M4 8h16v8H4zM9 12h6",
    pagelinks: "M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1",
    divider: "M3 12h18",
    spacer: "M12 4v16M8 8l4-4 4 4M8 16l4 4 4-4",
    http: "M12 3a9 9 0 100 18 9 9 0 000-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18",
    query: "M12 4c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3zM4 7v10c0 1.7 3.6 3 8 3s8-1.3 8-3V7M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
    output: "M8 9l-4 3 4 3M16 9l4 3-4 3M13.5 6l-3 12",
    assign: "M7 8a2.5 2.5 0 100-5 2.5 2.5 0 000 5zM3 13c.8-2 2.3-3 4-3s3.2 1 4 3M13 6h8v14h-8zM13 11h8M13 16h8",
    weekplan: "M4 5h16v15H4zM4 9h16M8 3v4M16 3v4M8 13h2M14 13h2M8 17h2M14 17h2",
    kanban: "M4 4h4v16H4zM10 4h4v10h-4zM16 4h4v7h-4z",
    details: "M4 5h16v5H4zM9 7.5l1.5 1 1.5-1M4 13h16M4 17h11",
    filter: "M4 5h16l-6 7v6l-4 2v-8z",
    calendar: "M4 5h16v15H4zM4 9h16M8 3v4M16 3v4M8 13h3v3H8z",
    checklist: "M4 6l2 2 3-3M4 12l2 2 3-3M4 18l2 2 3-3M12 7h8M12 13h8M12 19h8",
    sliders: "M4 7h16M4 12h16M4 17h16M9 5v4M15 10v4M7 15v4",
    custom: "M12 3l2.6 5.6 6 .7-4.4 4.2 1.1 6-5.3-3-5.3 3 1.1-6L3.4 9.3l6-.7z",
  };
  var SVG_NS = "http://www.w3.org/2000/svg";
  var gettext = window.gettext || function (text) { return text; };

  var types = {};
  cfg.blocks.forEach(function (b) { types[b.key] = b; });
  var layout = cfg.layout || [];
  var pageVersion = cfg.version || 1;
  var selectedId = null;
  var dirty = false;
  var saving = false;
  var previews = {};   // id -> zuletzt gerendertes HTML
  var previewTimer = null;
  var previewRun = 0;

  function el(tag, attrs) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === "text") node.textContent = attrs[key];
      else if (key === "class") node.className = attrs[key];
      else node.setAttribute(key, attrs[key]);
    });
    for (var i = 2; i < arguments.length; i++) {
      if (arguments[i]) node.appendChild(arguments[i]);
    }
    return node;
  }

  function icon(typeKey) {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", "bicon");
    svg.setAttribute("aria-hidden", "true");
    var path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", ICONS[typeKey] || ICONS.custom);
    svg.appendChild(path);
    return svg;
  }

  function uid() { return "b" + Math.random().toString(36).slice(2, 10); }

  function defaults(type) {
    var props = {};
    types[type].fields.forEach(function (f) { props[f.key] = f.default !== undefined ? f.default : ""; });
    return props;
  }

  function find(id) { return layout.filter(function (b) { return b.id === id; })[0]; }
  function entity(slug) { return cfg.entities.filter(function (e) { return e.slug === slug; })[0]; }

  // Zu welcher Tabelle gehört eine Feld-Einstellung? Standard ist die Einstellung „entity“;
  // mit spec.of eine andere Tabellen-Einstellung oder die Zieltabelle eines Verweisfelds.
  function fieldEntity(spec, block, depth) {
    var of = spec.of || "entity";
    var parent = (types[block.type].fields || []).filter(function (s) { return s.key === of; })[0];
    if (parent && parent.type === "field" && (depth || 0) < 3) {
      var owner = fieldEntity(parent, block, (depth || 0) + 1);
      var ref = owner && owner.fields.filter(function (f) { return f.key === block.props[of]; })[0];
      return ref && ref.reference ? entity(ref.reference) : null;
    }
    return entity(block.props[of]);
  }

  function dependsOnField(spec, block) {
    var parent = (types[block.type].fields || []).filter(function (s) { return s.key === spec.of; })[0];
    return parent && parent.type === "field";
  }

  function markDirty() {
    dirty = true;
    statusEl.textContent = gettext("Nicht gespeichert");
    schedulePreview();
  }

  function addBlock(type, index) {
    var props = defaults(type);
    // Gibt es nur eine Tabelle, ist sie die naheliegende Wahl.
    if ("entity" in props && cfg.entities.length === 1) props.entity = cfg.entities[0].slug;
    var block = { id: uid(), type: type, width: 12, props: props };
    layout.splice(index === undefined ? layout.length : index, 0, block);
    selectedId = block.id;
    markDirty();
    render();
    revealOnSmallScreen(block.id);
  }

  // Auf dem Handy stehen Arbeitsfläche, Einstellungen und Bausteine untereinander:
  // nach dem Hinzufügen zum neuen Baustein springen, nach dem Auswählen zu seinen Einstellungen.
  var narrow = window.matchMedia ? window.matchMedia("(max-width: 900px)") : { matches: false };
  function revealOnSmallScreen(id) {
    if (!narrow.matches) return;
    var el = document.querySelector('.dblock[data-id="' + id + '"]');
    if (el && el.scrollIntoView) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function addPreset(preset, index) {
    var block = { id: uid(), type: preset.type, width: preset.width || 12,
                  props: JSON.parse(JSON.stringify(preset.props || {})) };
    layout.splice(index === undefined ? layout.length : index, 0, block);
    selectedId = block.id;
    markDirty();
    render();
  }

  // ---------- Palette ----------
  function renderPalette() {
    var query = (search.value || "").trim().toLowerCase();
    palette.replaceChildren();
    var shown = 0;
    cfg.categories.forEach(function (category) {
      var items = cfg.blocks.filter(function (type) {
        return type.category === category.key &&
          (!query || (type.label + " " + type.hint).toLowerCase().indexOf(query) >= 0);
      });
      if (!items.length) return;
      palette.appendChild(el("h4", { text: category.label }));
      items.forEach(function (type) {
        shown++;
        var item = el("button", { class: "pal-item", type: "button", draggable: "true", title: type.hint || type.label },
          icon(type.key),
          el("span", { class: "pal-text" },
            el("span", { class: "pal-label", text: type.label }),
            type.hint ? el("span", { class: "pal-hint", text: type.hint }) : null));
        item.addEventListener("dragstart", function (e) {
          dragState = { kind: "new", key: type.key };
          e.dataTransfer.effectAllowed = "copy";
          e.dataTransfer.setData("text/plain", "new:" + type.key);
        });
        item.addEventListener("click", function () { addBlock(type.key); });
        palette.appendChild(item);
      });
    });
    // Vorlagen: fertig eingestellte Bausteine
    var presets = cfg.presets.filter(function (preset) {
      return !query || (preset.name + " " + preset.hint).toLowerCase().indexOf(query) >= 0;
    });
    if (presets.length) palette.appendChild(el("h4", { text: gettext("Vorlagen") }));
    presets.forEach(function (preset) {
      shown++;
      var item = el("button", { class: "pal-item", type: "button", draggable: "true", title: preset.hint || preset.name },
        icon(preset.type),
        el("span", { class: "pal-text" },
          el("span", { class: "pal-label", text: preset.name }),
          preset.hint ? el("span", { class: "pal-hint", text: preset.hint }) : null));
      item.addEventListener("dragstart", function (e) {
        dragState = { kind: "preset", id: preset.id };
        e.dataTransfer.effectAllowed = "copy";
        e.dataTransfer.setData("text/plain", "preset:" + preset.id);
      });
      item.addEventListener("click", function () { addPreset(preset); });
      palette.appendChild(item);
    });
    if (!shown) palette.appendChild(el("p", { class: "muted small", text: gettext("Kein Baustein passt zur Suche.") }));
  }
  search.addEventListener("input", renderPalette);

  // ---------- Arbeitsfläche ----------
  var dragState = null;

  function clearDropIndicators() {
    canvas.classList.remove("over");
    canvas.querySelectorAll(".drop-before, .drop-after").forEach(function (el) {
      el.classList.remove("drop-before", "drop-after");
    });
  }

  function clearDragState() {
    clearDropIndicators();
    canvas.querySelectorAll(".is-drag-source").forEach(function (el) {
      el.classList.remove("is-drag-source");
    });
    dragState = null;
  }

  function isDropAfter(e, node, block) {
    var rect = node.getBoundingClientRect();
    if (block.width < 12) return e.clientX > rect.left + rect.width / 2;
    return e.clientY > rect.top + rect.height / 2;
  }

  function autoScroll(e) {
    var margin = 72;
    if (e.clientY < margin) window.scrollBy(0, -14);
    else if (e.clientY > window.innerHeight - margin) window.scrollBy(0, 14);
  }

  function focusBlock(id) {
    var node = canvas.querySelector('.dblock[data-id="' + id + '"]');
    if (node) node.focus();
  }

  function focusBlockAt(index) {
    if (index < 0 || index >= layout.length) return;
    focusBlock(layout[index].id);
  }

  function handleDrop(e, index) {
    e.preventDefault();
    e.stopPropagation();
    var data = e.dataTransfer.getData("text/plain") || "";
    clearDragState();
    if (data.indexOf("new:") === 0 && types[data.slice(4)]) {
      addBlock(data.slice(4), index);
    } else if (data.indexOf("preset:") === 0) {
      var preset = cfg.presets.filter(function (p) { return String(p.id) === data.slice(7); })[0];
      if (preset) addPreset(preset, index);
    } else if (data.indexOf("move:") === 0) {
      var from = layout.indexOf(find(data.slice(5)));
      if (from < 0) return;
      var to = from < index ? index - 1 : index;
      if (to === from) return;
      var block = layout.splice(from, 1)[0];
      layout.splice(to, 0, block);
      markDirty();
      render();
    }
  }

  function renderCanvas() {
    canvas.replaceChildren();
    if (!layout.length) {
      canvas.appendChild(el("div", { class: "canvas-hint" },
        el("strong", { text: gettext("Diese Seite ist noch leer") }),
        el("span", { text: gettext("Ziehe links einen Baustein hierher oder klicke ihn an.") })));
    }
    layout.forEach(function (block, index) {
      var type = types[block.type];
      var body = el("div", { class: "dblock-body" });
      body.inert = true;  // Vorschau ist nicht bedienbar: Links und Formulare bleiben ohne Wirkung
      if (previews[block.id] !== undefined) body.innerHTML = previews[block.id];
      else body.appendChild(el("span", { class: "muted small", text: gettext("Vorschau wird geladen …") }));
      var node = el("div", {
          class: "dblock col col-" + block.width + (block.id === selectedId ? " selected" : ""),
          draggable: "true", tabindex: "0", "aria-label": type.label, "data-id": block.id,
        },
        el("div", { class: "dblock-type" }, icon(block.type), el("span", { text: type.label }),
          block.name ? el("code", { class: "key", text: block.name }) : null,
          block.refresh ? el("span", { class: "dblock-refresh", text: "↻ " + block.refresh + " s" }) : null),
        body);
      node.addEventListener("dragstart", function (e) {
        dragState = { kind: "move", id: block.id };
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", "move:" + block.id);
        window.requestAnimationFrame(function () {
          if (dragState && dragState.id === block.id) node.classList.add("is-drag-source");
        });
      });
      node.addEventListener("dragover", function (e) {
        e.preventDefault();
        e.stopPropagation();
        e.dataTransfer.dropEffect = dragState && dragState.kind === "move" ? "move" : "copy";
        autoScroll(e);
        clearDropIndicators();
        if (dragState && dragState.kind === "move" && dragState.id === block.id) return;
        node.classList.add(isDropAfter(e, node, block) ? "drop-after" : "drop-before");
      });
      node.addEventListener("dragleave", function (e) {
        if (!e.relatedTarget || !node.contains(e.relatedTarget)) {
          node.classList.remove("drop-before", "drop-after");
        }
      });
      node.addEventListener("drop", function (e) {
        var targetIndex = isDropAfter(e, node, block) ? index + 1 : index;
        handleDrop(e, targetIndex);
      });
      node.addEventListener("click", function () { select(block.id); });
      node.addEventListener("keydown", function (e) {
        if (e.target !== node) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          select(block.id, true);
        } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
          e.preventDefault();
          if (e.altKey || e.ctrlKey || e.metaKey) move(block, -1, true);
          else focusBlockAt(index - 1);
        } else if (e.key === "ArrowDown" || e.key === "ArrowRight") {
          e.preventDefault();
          if (e.altKey || e.ctrlKey || e.metaKey) move(block, 1, true);
          else focusBlockAt(index + 1);
        } else if (e.key === "Delete" || e.key === "Backspace") {
          e.preventDefault();
          removeBlock(block, true);
        } else if (e.key === "Escape" && selectedId) {
          e.preventDefault();
          selectedId = null;
          render();
          focusBlock(block.id);
        }
      });
      canvas.appendChild(node);
    });
  }

  canvas.addEventListener("dragover", function (e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = dragState && dragState.kind === "move" ? "move" : "copy";
    autoScroll(e);
    clearDropIndicators();
    canvas.classList.add("over");
  });
  canvas.addEventListener("dragleave", function (e) {
    if (!e.relatedTarget || !canvas.contains(e.relatedTarget)) canvas.classList.remove("over");
  });
  canvas.addEventListener("drop", function (e) { handleDrop(e, layout.length); });
  document.addEventListener("dragend", clearDragState);

  function select(id, keepFocus) {
    selectedId = id;
    render();
    if (keepFocus) focusBlock(id);
    if (narrow.matches) {
      var panel = document.getElementById("props");
      if (panel && panel.scrollIntoView) panel.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  // ---------- Vorschau vom Server ----------
  function post(url, payload) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": root.dataset.csrf },
      body: JSON.stringify(payload),
    }).then(function (response) {
      return response.json().catch(function () { return { error: response.statusText }; }).then(function (data) {
        data.status = response.status;
        return data;
      });
    });
  }

  function loadPreview() {
    var run = ++previewRun;
    post(root.dataset.previewUrl, { layout: layout })
      .then(function (data) {
        if (!data.ok || run !== previewRun) return;  // inzwischen wurde weitergearbeitet
        previews = data.blocks;
        renderCanvas();
      })
      .catch(function () { /* Vorschau ist Komfort; Speichern funktioniert trotzdem */ });
  }

  function schedulePreview() {
    window.clearTimeout(previewTimer);
    previewTimer = window.setTimeout(loadPreview, 300);
  }

  // ---------- Einstellungen des gewählten Bausteins ----------
  function optionList(spec, block) {
    switch (spec.type) {
      case "select": return spec.options;
      case "entity": return [["", gettext("– wählen –")]].concat(cfg.entities.map(function (e) { return [e.slug, e.name]; }));
      case "field":
        var ent = fieldEntity(spec, block);
        return [["", gettext("– wählen –")]].concat((ent ? ent.fields : []).map(function (f) { return [f.key, f.label]; }));
      case "page": return [["", gettext("– wählen –")]].concat(cfg.pages.map(function (p) { return [p.slug, p.title]; }));
      case "action": return [["", gettext("– wählen –")]].concat(cfg.actions.map(function (a) { return [a.name, a.label]; }));
      case "script": return [["", gettext("– wählen –")]].concat(cfg.scripts.map(function (a) { return [a.slug, a.name]; }));
      case "query": return [["", gettext("– wählen –")]].concat(cfg.queries.map(function (a) { return [a.slug, a.name]; }));
    }
    return null;
  }

  function selectInput(options, current, id) {
    var input = el("select", { id: id });
    options.forEach(function (option) {
      var node = el("option", { value: String(option[0]), text: option[1] });
      if (String(option[0]) === String(current)) node.selected = true;
      input.appendChild(node);
    });
    return input;
  }

  function propRow(block, spec) {
    // Beim Button nur die Einstellung zeigen, die zum gewählten Ziel passt.
    if (block.type === "button" && ["page", "url", "script", "action"].indexOf(spec.key) >= 0 && block.props.target !== spec.key) {
      return null;
    }
    // Das Zahlenfeld wird nur für Summe und Durchschnitt gebraucht.
    if (spec.key === "field" && "aggregate" in block.props && block.props.aggregate === "count") {
      return null;
    }
    // Feld einer verknüpften Tabelle (z. B. Priorität der Linie) erst zeigen, wenn es die Tabelle gibt.
    if (spec.type === "field" && spec.of && dependsOnField(spec, block) && !fieldEntity(spec, block)) {
      return null;
    }
    var id = "prop-" + spec.key;
    var value = block.props[spec.key];
    var options = optionList(spec, block);
    var input;
    if (spec.type === "checkbox") {
      input = el("input", { type: "checkbox", id: id });
      input.checked = !!value;
    } else if (options) {
      input = selectInput(options, value, id);
    } else if (spec.type === "textarea") {
      input = el("textarea", { id: id, rows: "5" });
      input.value = value || "";
    } else {
      input = el("input", { type: spec.type === "number" ? "number" : "text", id: id });
      input.value = value === undefined ? "" : value;
    }
    input.addEventListener(options || spec.type === "checkbox" ? "change" : "input", function () {
      block.props[spec.key] = spec.type === "checkbox" ? input.checked : input.value;
      markDirty();
      if (spec.type === "entity" || spec.type === "field" || spec.key === "target" || spec.key === "aggregate") renderProps();
    });
    if (spec.type === "checkbox") {
      var label = el("label", { for: id });
      label.appendChild(input);
      label.appendChild(document.createTextNode(spec.label));
      return el("div", { class: "prop check-prop" }, label);
    }
    var row = el("div", { class: "prop" }, el("label", { for: id, text: spec.label }), input);
    if (spec.type === "entity" && !cfg.entities.length) {
      row.appendChild(el("p", { class: "muted small", text: gettext("Diese App hat noch keine Tabelle. Lege zuerst eine an.") }));
    }
    return row;
  }

  function actionButton(text, handler, extraClass) {
    var button = el("button", { type: "button", class: "btn btn-secondary btn-small" + (extraClass || ""), text: text });
    button.addEventListener("click", handler);
    return button;
  }

  function move(block, delta, keepFocus) {
    var from = layout.indexOf(block);
    var to = from + delta;
    if (to < 0 || to >= layout.length) return;
    layout.splice(from, 1);
    layout.splice(to, 0, block);
    markDirty();
    render();
    if (keepFocus) focusBlock(block.id);
  }

  function removeBlock(block, keepFocus) {
    var index = layout.indexOf(block);
    if (index < 0) return;
    layout.splice(index, 1);
    if (selectedId === block.id) selectedId = null;
    markDirty();
    render();
    if (keepFocus) {
      var next = layout[index] || layout[index - 1];
      if (next) focusBlock(next.id);
    }
  }

  function renderProps() {
    propsEl.replaceChildren();
    var block = find(selectedId);
    if (!block) {
      propsEl.appendChild(el("h4", { text: gettext("Einstellungen") }));
      propsEl.appendChild(el("p", { class: "muted small", text: gettext("Wähle einen Baustein auf der Seite aus, um ihn einzustellen.") }));
      return;
    }
    var type = types[block.type];
    propsEl.appendChild(el("div", { class: "props-head" }, icon(block.type), el("strong", { text: type.label })));
    if (type.hint) propsEl.appendChild(el("p", { class: "muted small", text: type.hint }));

    var width = selectInput(cfg.widths, block.width, "prop-width");
    width.addEventListener("change", function () {
      block.width = parseInt(width.value, 10);
      markDirty();
      renderCanvas();
    });
    propsEl.appendChild(el("div", { class: "prop" }, el("label", { for: "prop-width", text: gettext("Breite") }), width));

    // Name: damit Skripte den Baustein füllen können (ui.set("name", …)).
    var nameInput = el("input", { type: "text", id: "prop-name", maxlength: "40", placeholder: gettext("z. B. ergebnis") });
    nameInput.value = block.name || "";
    nameInput.addEventListener("input", function () {
      var cleaned = nameInput.value.toLowerCase().replace(/[^a-z0-9_]/g, "_").replace(/^[^a-z]+/, "");
      if (cleaned !== nameInput.value) nameInput.value = cleaned;
      block.name = cleaned;
      markDirty();
    });
    propsEl.appendChild(el("div", { class: "prop" },
      el("label", { for: "prop-name", text: gettext("Name für Skripte") }), nameInput,
      el("span", { class: "muted small prop-help", text: gettext("Optional. Skripte füllen den Baustein über diesen Namen.") })));

    var refresh = selectInput(cfg.refresh, block.refresh || 0, "prop-refresh");
    refresh.addEventListener("change", function () {
      block.refresh = parseInt(refresh.value, 10) || 0;
      markDirty();
    });
    propsEl.appendChild(el("div", { class: "prop" },
      el("label", { for: "prop-refresh", text: gettext("Automatisch aktualisieren") }), refresh));

    type.fields.forEach(function (spec) {
      var row = propRow(block, spec);
      if (row) propsEl.appendChild(row);
    });

    propsEl.appendChild(el("div", { class: "prop-actions" },
      actionButton(gettext("Nach vorn"), function () { move(block, -1); }),
      actionButton(gettext("Nach hinten"), function () { move(block, 1); }),
      actionButton(gettext("Duplizieren"), function () {
        var copy = JSON.parse(JSON.stringify(block));
        copy.id = uid();
        layout.splice(layout.indexOf(block) + 1, 0, copy);
        selectedId = copy.id;
        markDirty();
        render();
      }),
      actionButton(gettext("Entfernen"), function () { removeBlock(block, false); }, " danger")));

    // Als Vorlage speichern: der Baustein mit seinen jetzigen Einstellungen wird wiederverwendbar.
    var nameInput = el("input", { type: "text", id: "preset-name", maxlength: "80", placeholder: gettext("Name der Vorlage") });
    var note = el("p", { class: "muted small", role: "status" });
    var saveButton = actionButton(gettext("Als Vorlage speichern"), function () {
      post(root.dataset.presetUrl, { name: nameInput.value, block: block }).then(function (data) {
        if (!data.ok) { note.textContent = data.error || gettext("Speichern fehlgeschlagen. Bitte erneut versuchen."); return; }
        cfg.presets.push(data.preset);
        nameInput.value = "";
        note.textContent = gettext("Vorlage gespeichert. Sie steht links unter „Vorlagen“.");
        renderPalette();
      }).catch(function () { note.textContent = gettext("Speichern fehlgeschlagen. Bitte erneut versuchen."); });
    });
    propsEl.appendChild(el("div", { class: "preset-box" },
      el("label", { for: "preset-name", text: gettext("Wiederverwenden") }), nameInput, saveButton, note));
  }

  function render() {
    renderCanvas();
    renderProps();
  }

  // ---------- Speichern ----------
  function save() {
    if (saving) return;
    saving = true;
    statusEl.textContent = gettext("Speichere …");
    post(window.location.href, {
      title: titleEl.value,
      show_in_nav: navEl.checked,
      public: publicEl ? publicEl.checked : false,
      layout: layout,
      version: pageVersion,
    })
      .then(function (data) {
        saving = false;
        if (data.status >= 200 && data.status < 300 && data.ok) {
          layout = data.layout;
          if (typeof data.version === "number") pageVersion = data.version;
          dirty = false;
          if (conflictNote) conflictNote.hidden = true;
          statusEl.textContent = gettext("Gespeichert");
          render();
          return;
        }
        if (data.status === 409 || data.conflict) {
          var message = data.error || gettext("Diese Seite wurde inzwischen von jemand anderem gespeichert. Bitte lade die Seite neu, um keine Änderungen zu überschreiben.");
          statusEl.textContent = gettext("Konflikt – nicht gespeichert");
          if (conflictText) conflictText.textContent = message;
          if (conflictNote) conflictNote.hidden = false;
          if (window.BaukastenDialog && typeof window.BaukastenDialog.confirm === "function") {
            window.BaukastenDialog.confirm({
              title: gettext("Speichern nicht möglich – Konflikt"),
              text: message,
              ok: gettext("Seite neu laden"),
              cancel: gettext("Auf der Seite bleiben"),
              tone: "warning",
            }).then(function (reloadNow) {
              if (reloadNow) {
                dirty = false;
                window.location.reload();
              }
            });
          }
          return;
        }
        statusEl.textContent = data.error || gettext("Speichern fehlgeschlagen. Bitte erneut versuchen.");
      })
      .catch(function () {
        saving = false;
        statusEl.textContent = gettext("Speichern fehlgeschlagen. Bitte erneut versuchen.");
      });
  }

  document.getElementById("save").addEventListener("click", save);
  if (conflictReload) {
    conflictReload.addEventListener("click", function () {
      dirty = false;
      window.location.reload();
    });
  }
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key && e.key.toLowerCase() === "s") {
      e.preventDefault();
      save();
    }
  });
  titleEl.addEventListener("input", function () { dirty = true; statusEl.textContent = gettext("Nicht gespeichert"); });
  navEl.addEventListener("change", function () { dirty = true; statusEl.textContent = gettext("Nicht gespeichert"); });
  if (publicEl) {
    publicEl.addEventListener("change", function () {
      dirty = true;
      statusEl.textContent = gettext("Nicht gespeichert");
      if (publicNote) publicNote.hidden = !publicEl.checked;
    });
  }
  window.addEventListener("beforeunload", function (e) {
    if (dirty) { e.preventDefault(); e.returnValue = ""; }
  });

  renderPalette();
  render();
  loadPreview();
})();
