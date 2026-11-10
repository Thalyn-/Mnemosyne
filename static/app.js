(() => {
  "use strict";
  const $ = (selector, root = document) => root.querySelector(selector);
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
  const safeUrl = (value) => {
    try {
      const url = new URL(value);
      return ["https:", "http:"].includes(url.protocol) ? url.href : "#";
    } catch { return "#"; }
  };
  let current = null;
  let map = null;
  let mapMarkers = null;
  let showAllEvents = false;
  let versions = [];

  async function request(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Erreur (${response.status}).`);
    return data;
  }

  function collectNotes() {
    if (!current) return;
    const traces = $("#traces-input");
    const questions = $("#questions-input");
    if (traces) current.data.traces = traces.value.split("\n").map((line) => line.trim()).filter(Boolean);
    if (questions) current.data.questions = questions.value.split("\n").map((line) => line.trim()).filter(Boolean);
  }

  function showView(name) {
    document.querySelectorAll(".view").forEach((view) => {
      view.hidden = view.id !== `view-${name}`;
    });
    document.querySelectorAll(".nav-button").forEach((button) => {
      button.classList.toggle("active", button.dataset.view === name);
    });
    if (name === "archives") loadArchives();
    if (name === "compare") loadCompareChoices();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  document.querySelectorAll(".nav-button").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });

  $("#search-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = $("#search-status");
    const query = $("#query").value.trim();
    status.classList.remove("error");
    status.textContent = "Recherche des catalogues et constitution du dossier…";
    $("#welcome").hidden = true;
    try {
      const item = await request("/api/research", {
        method: "POST", body: JSON.stringify({ query }),
      });
      openVersion(item);
      await loadArchives();
    } catch (error) {
      status.classList.add("error");
      status.textContent = error.message;
      $("#welcome").hidden = false;
    }
  });

  function sourceLink(name, type, url, mode) {
    return `<a class="source-card" href="${escapeHtml(safeUrl(url))}" target="_blank" rel="noopener noreferrer">
      <span><strong>${escapeHtml(name)}</strong><small>${escapeHtml(type)}</small></span>
      <span class="source-mode">${mode === "automatique" ? "INTERROGÉ" : "OUVRIR ↗"}</span></a>`;
  }

  function renderResults(data) {
    const rows = Object.entries(data.results || {}).flatMap(([name, result]) =>
      (result.records || []).map((record) =>
        `<article class="result-item"><a href="${escapeHtml(safeUrl(record.url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(record.title)}</a>
        <small>${escapeHtml(name)} · ${escapeHtml(result.count)} résultat(s) signalé(s)</small></article>`));
    return rows.length ? `<div class="result-list">${rows.join("")}</div>` :
      `<p class="subtle">Aucun document retourné par les catalogues interrogés ; utilisez les liens de recherche ci-dessus.</p>`;
  }

  function renderTimeline(data) {
    const events = data.timeline || [];
    if (!events.length) return `<p class="empty">Aucun repère chronologique exploitable n’a été trouvé. Vérifiez la page retenue et consultez les sources.</p>`;
    const selected = showAllEvents ? events : events.slice(0, 10);
    const rows = selected.map((event) => `<div class="event">
      <strong>${escapeHtml(event.year)}</strong><p>${escapeHtml(event.text)}</p>
      ${event.source ? `<a href="${escapeHtml(safeUrl(event.source))}" target="_blank" rel="noopener noreferrer">Source ↗</a>` : ""}
      </div>`).join("");
    const more = events.length > 10
      ? `<button class="more-button" id="timeline-toggle">${showAllEvents ? "Réduire" : `Tout voir (${events.length})`}</button>` : "";
    return `<div class="timeline">${rows}</div>${more}`;
  }

  function renderPeople(data) {
    const people = data.people || [];
    if (!people.length) return `<p class="empty">Aucune personnalité liée trouvée dans les données interrogées. Ce résultat ne signifie pas qu’il n’en existe pas.</p>`;
    return `<div class="people-grid">${people.map((person) => `<article class="person-card">
      <strong>${escapeHtml(person.name)}</strong><small>${escapeHtml(person.detail)}</small>
      <a href="${escapeHtml(safeUrl(person.source))}" target="_blank" rel="noopener noreferrer">Référence Wikidata ↗</a>
      </article>`).join("")}</div>`;
  }

  function renderPlaces(data) {
    const places = data.places || [];
    if (!places.length) return `<p class="empty">Aucun lieu patrimonial associé trouvé. Complétez cette liste après vérification des sources locales.</p>`;
    return `<div class="place-grid">${places.map((place, index) => `<article class="place-card">
      <span class="rank">${String(index + 1).padStart(2, "0")}</span><strong>${escapeHtml(place.name)}</strong>
      <small>${escapeHtml(place.detail)}</small>
      <a href="${escapeHtml(safeUrl(place.source))}" target="_blank" rel="noopener noreferrer">Voir la référence ↗</a><br>
      <select aria-label="Importance de ${escapeHtml(place.name)}" data-place="${index}">
        ${["indispensable", "recommandé", "en bonus"].map((rank) =>
          `<option ${place.category === rank ? "selected" : ""}>${rank}</option>`).join("")}
      </select></article>`).join("")}</div>`;
  }

  function renderPersee(data) {
    const results = data.persee || [];
    if (!results.length) return "";
    const displayed = results.slice(0, 10);
    const cards = `<div class="result-list">${displayed.map((article) =>
      `<article class="result-item"><a href="${escapeHtml(safeUrl(article.url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(article.title)}</a><small>Persée · article à consulter</small></article>`
    ).join("")}</div>`;
    const more = data.perseeCount > 10
      ? `<p><a class="more-button" href="${escapeHtml(safeUrl(data.perseeUrl))}" target="_blank" rel="noopener noreferrer">Tout voir dans Persée (${escapeHtml(data.perseeCount)} résultats) ↗</a></p>`
      : "";
    return cards + more;
  }

  function renderDossier(item) {
    current = item;
    const data = item.data;
    const page = data.page || {};
    $("#welcome").hidden = true;
    const dossier = $("#dossier");
    dossier.hidden = false;
    dossier.innerHTML = `
      <div class="dossier-top"><div><div class="eyebrow"><span class="eyebrow-line"></span> DOSSIER DOCUMENTAIRE · VERSION ${item.id}</div>
        <h2>${escapeHtml(page.title || data.query)}</h2>
        <p>Recherche : ${escapeHtml(data.query)} · Archivé le ${escapeHtml(new Date(item.cree_le).toLocaleString("fr-FR"))}</p>
        ${page.url ? `<a class="subtle" href="${escapeHtml(safeUrl(page.url))}" target="_blank" rel="noopener noreferrer">Page retenue : ${escapeHtml(page.title)} ↗</a>` : ""}
      </div><div class="actions">
        <button class="button-light" id="refresh-button">↻ Actualiser · nouvelle version</button>
        <button class="button-light" id="save-button">Enregistrer mes notes</button>
        <button class="button-light" id="print-button">Exporter en PDF</button>
        <button class="button-light" id="export-md">Exporter en Markdown</button>
        <button class="button-light" id="export-json">Exporter en JSON</button>
        <button class="button-light" id="export-html">Exporter en HTML</button>
      </div></div>
      <div class="notice"><strong>À vérifier :</strong> les pistes de recherche et les faits extraits de bases de données ne remplacent pas la lecture des documents. La chronologie provient de la page de synthèse indiquée, pas d’une validation historienne.</div>
      ${(data.errors || []).length ? `<div class="notice error-list"><strong>Services indisponibles :</strong><br>${data.errors.map(escapeHtml).join("<br>")}</div>` : ""}
      <section class="section"><div class="section-head"><div><h3><span class="section-index">01</span>Sources documentaires</h3><p>Les liens ouvrent les catalogues ; seuls les services indiqués sont interrogés automatiquement.</p></div></div>
        <div class="source-grid">${(data.sources || []).map((source) => sourceLink(source.name, source.type, source.url, source.mode)).join("")}</div>
        ${renderResults(data)}</section>
      <section class="section"><div class="section-head"><div><h3><span class="section-index">02</span>Repères chronologiques</h3><p>${(data.timeline || []).length} piste(s) datée(s) · source : page de synthèse retenue</p></div>
        <button class="persée-button" id="persee-button">Chercher des articles dans Persée ↗</button></div>
        <div id="persee-status" class="status"></div><div id="persee-results">${renderPersee(data)}</div>
        ${renderTimeline(data)}</section>
      <section class="section"><div class="section-head"><div><h3><span class="section-index">03</span>Personnalités</h3><p>${(data.people || []).length} nom(s) liés dans Wikidata · sélection non exhaustive.</p></div></div>${renderPeople(data)}</section>
      <section class="section"><div class="section-head"><div><h3><span class="section-index">04</span>Lieux à découvrir</h3><p>Classez les pistes selon leur intérêt après vérification.</p></div></div>${renderPlaces(data)}</section>
      <section class="section"><div class="section-head"><div><h3><span class="section-index">05</span>Carte et traces disparues</h3><p>Les marqueurs correspondent aux lieux renseignés ci-dessus.</p></div></div>
        <div class="map-tools"><label for="historic-layer">Calque historique</label><select id="historic-layer">
          <option value="">Aucun — plan OpenStreetMap</option><option value="cassini">Carte de Cassini · visibilité à confirmer</option>
          <option value="etatmajor">Carte d’état-major · visibilité à confirmer</option><option value="ortho">Photographies aériennes · service actuel</option>
        </select><label for="layer-opacity">Transparence <input id="layer-opacity" type="range" min="0" max="100" value="65"></label></div>
        <div id="map" role="application" aria-label="Carte interactive des lieux patrimoniaux"></div>
        <p class="map-note" id="map-note">Les cartes anciennes dépendent de la disponibilité des couches du Géoportail. Les emplacements des traces disparues sont à documenter ci-dessous.</p>
        <label class="subtle" for="traces-input">Traces disparues ou transformées · une entrée par ligne (lieu, emplacement ou référence)</label>
        <textarea id="traces-input" class="editable" placeholder="Ex. Ancienne enceinte — emplacement approximatif, à confirmer dans les plans d’archives.">${escapeHtml((data.traces || []).join("\n"))}</textarea>
      </section>
      <section class="section"><div class="section-head"><div><h3><span class="section-index">06</span>Questions ouvertes</h3><p>Indiquez les débats documentés, avec leurs références bibliographiques.</p></div></div>
        <label class="subtle" for="questions-input">Questions historiques, culturelles ou religieuses · une question par ligne</label>
        <textarea id="questions-input" class="editable" placeholder="Ajoutez une question débattue et une référence vérifiable.">${escapeHtml((data.questions || []).join("\n"))}</textarea>
      </section>`;
    $("#timeline-toggle")?.addEventListener("click", () => {
      showAllEvents = !showAllEvents;
      renderDossier(current);
    });
    $("#save-button").addEventListener("click", saveNotes);
    $("#refresh-button").addEventListener("click", refresh);
    $("#print-button").addEventListener("click", () => window.print());
    $("#export-md").addEventListener("click", exportMarkdown);
    $("#export-json").addEventListener("click", () => {
      collectNotes();
      download(JSON.stringify(current.data, null, 2), filename("json"), "application/json;charset=utf-8");
    });
    $("#export-html").addEventListener("click", exportHtml);
    $("#persee-button").addEventListener("click", searchPersee);
    document.querySelectorAll("[data-place]").forEach((select) => select.addEventListener("change", () => {
      current.data.places[Number(select.dataset.place)].category = select.value;
    }));
    setupMap(data);
    dossier.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function openVersion(item) {
    $("#search-status").textContent = "";
    showAllEvents = false;
    showView("research");
    renderDossier(item);
  }

  function setupMap(data) {
    if (map) { map.remove(); map = null; mapMarkers = null; }
    if (!window.L) {
      $("#map-note").textContent = "La carte nécessite une connexion pour charger Leaflet et OpenStreetMap.";
      return;
    }
    const page = data.page || {};
    const lat = Number(page.lat);
    const lon = Number(page.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      $("#map-note").textContent = "Aucune coordonnée fiable n’a été trouvée pour cette page.";
      return;
    }
    map = L.map("map").setView([lat, lon], 13);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);
    mapMarkers = L.layerGroup().addTo(map);
    L.marker([lat, lon]).bindPopup(`<strong>${escapeHtml(page.title || data.query)}</strong><br>Centre indiqué par la source`).addTo(mapMarkers);
    (data.places || []).forEach((place, index) => {
      if (Number.isFinite(place.lat) && Number.isFinite(place.lon)) {
        const icon = L.divIcon({
          className: "",
          html: `<span class="map-number">${index + 1}</span>`,
          iconSize: [26, 26],
          iconAnchor: [13, 13],
        });
        L.marker([place.lat, place.lon], { icon })
          .bindPopup(`<strong>${index + 1}. ${escapeHtml(place.name)}</strong><br>${escapeHtml(place.category || "À vérifier")}`)
          .addTo(mapMarkers);
      }
    });
    const layers = {
      cassini: ["GEOGRAPHICALGRIDSYSTEMS.MAPS.CASSINI", "image/jpeg"],
      etatmajor: ["GEOGRAPHICALGRIDSYSTEMS.MAPS.ETATMAJOR40", "image/jpeg"],
      ortho: ["ORTHOIMAGERY.ORTHOPHOTOS", "image/jpeg"],
    };
    let overlay = null;
    $("#historic-layer").addEventListener("change", (event) => {
      if (overlay) map.removeLayer(overlay);
      overlay = null;
      const selected = layers[event.target.value];
      if (!selected) return;
      const [layer, format] = selected;
      overlay = L.tileLayer(
        `https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=${layer}&STYLE=normal&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=${format}`,
        { opacity: Number($("#layer-opacity").value) / 100, maxZoom: 18,
          attribution: '&copy; <a href="https://geoservices.ign.fr/">IGN</a>' },
      );
      overlay.on("tileerror", () => {
        $("#map-note").textContent = "Cette couche historique n’est peut-être pas disponible pour cette échelle ou cette zone. Consultez le catalogue de l’IGN.";
      });
      overlay.addTo(map);
    });
    $("#layer-opacity").addEventListener("input", (event) => {
      if (overlay) overlay.setOpacity(Number(event.target.value) / 100);
    });
    setTimeout(() => map?.invalidateSize(), 100);
  }

  async function saveNotes() {
    if (!current) return;
    collectNotes();
    const button = $("#save-button");
    button.disabled = true;
    try {
      current = await request(`/api/versions/${current.id}/save`, {
        method: "POST", body: JSON.stringify({ data: current.data }),
      });
      button.textContent = "Notes enregistrées";
      setTimeout(() => { if (button.isConnected) button.textContent = "Enregistrer mes notes"; }, 1800);
    } catch (error) {
      button.disabled = false;
      alert(error.message);
    }
  }

  async function refresh() {
    await saveNotes();
    const button = $("#refresh-button");
    button.disabled = true;
    button.textContent = "Actualisation en cours…";
    try {
      const next = await request(`/api/versions/${current.id}/refresh`, {
        method: "POST", body: JSON.stringify({}),
      });
      openVersion(next);
      await loadArchives();
    } catch (error) {
      button.disabled = false;
      button.textContent = "↻ Actualiser · nouvelle version";
      alert(error.message);
    }
  }

  async function searchPersee() {
    const button = $("#persee-button");
    const status = $("#persee-status");
    const words = (current.data.timeline || []).flatMap((item) =>
      item.text.match(/[^\W\d_]{5,}/gu) || []);
    const keywords = [...new Set(words.map((word) => word.toLocaleLowerCase("fr-FR")))].slice(0, 5);
    const query = [current.data.query.split(",")[0], ...keywords].join(" ");
    button.disabled = true;
    status.textContent = "Recherche des articles dans le catalogue Persée…";
    status.classList.remove("error");
    try {
      const result = await request(`/api/persee?q=${encodeURIComponent(query)}`);
      current.data.persee = result.records || [];
      current.data.perseeCount = result.count || 0;
      current.data.perseeUrl = result.url;
      $("#persee-results").innerHTML = `${renderPersee(current.data)}
        <p class="subtle">${escapeHtml(result.count)} résultat(s) signalé(s), au plus 30 récupérés.</p>`;
      await saveNotes();
      status.textContent = result.count > 10
        ? `${result.count} articles trouvés : les dix premiers sont affichés, le lien « Tout voir » ouvre la recherche complète.`
        : `${result.count} article(s) trouvé(s).`;
    } catch (error) {
      status.classList.add("error");
      status.textContent = error.message;
      const fallback = `https://www.persee.fr/search?${new URLSearchParams({ q: query, ta: "article" })}`;
      $("#persee-results").innerHTML = `<p class="subtle"><a href="${escapeHtml(safeUrl(fallback))}" target="_blank" rel="noopener noreferrer">Ouvrir cette recherche dans Persée ↗</a></p>`;
    } finally { button.disabled = false; }
  }

  async function loadArchives() {
    try {
      versions = await request("/api/versions");
      $("#archive-count").textContent = versions.length;
      const list = $("#archive-list");
      if (!versions.length) {
        list.innerHTML = `<div class="empty">Aucun dossier archivé pour le moment. Lancez une recherche pour commencer votre bibliothèque.</div>`;
        return;
      }
      const groups = new Map();
      versions.forEach((item) => {
        if (!groups.has(item.dossier)) groups.set(item.dossier, []);
        groups.get(item.dossier).push(item);
      });
      list.innerHTML = [...groups.values()].map((items) => {
        const latest = items[0];
        return `<article class="archive-item"><div><h3>${escapeHtml(latest.query || "Dossier sans titre")}</h3>
          <p>${items.length} version(s) · dernière actualisation ${escapeHtml(new Date(latest.cree_le).toLocaleString("fr-FR"))}</p></div>
          <div class="archive-buttons"><button class="button-light" data-open="${latest.id}">Ouvrir</button>
          <button class="button-light" data-refresh="${latest.id}">↻ Actualiser</button>
          ${items.slice(1).map((item) => `<button class="button-outline" data-open="${item.id}">Version ${item.id}</button>`).join("")}
          </div></article>`;
      }).join("");
      list.querySelectorAll("[data-open]").forEach((button) =>
        button.addEventListener("click", () => openSaved(Number(button.dataset.open))));
      list.querySelectorAll("[data-refresh]").forEach((button) =>
        button.addEventListener("click", () => refreshSaved(Number(button.dataset.refresh))));
    } catch (error) {
      $("#archive-list").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
    }
  }

  async function openSaved(id) {
    try {
      const item = await request(`/api/versions/${id}`);
      $("#query").value = item.data.query;
      showView("research");
      renderDossier(item);
    } catch (error) { alert(error.message); }
  }

  async function refreshSaved(id) {
    try {
      const item = await request(`/api/versions/${id}`);
      const next = await request(`/api/versions/${id}/refresh`, {
        method: "POST", body: JSON.stringify({}),
      });
      await loadArchives();
      openVersion(next);
    } catch (error) { alert(error.message); }
  }

  async function loadCompareChoices() {
    await loadArchives();
    const choices = versions.map((item) =>
      `<option value="${item.id}">${escapeHtml(item.query)} · version ${item.id}</option>`).join("");
    $("#compare-a").innerHTML = choices || `<option value="">Aucun dossier archivé</option>`;
    $("#compare-b").innerHTML = choices || `<option value="">Aucun dossier archivé</option>`;
    if (versions.length > 1) $("#compare-b").selectedIndex = 1;
  }

  $("#compare-button").addEventListener("click", async () => {
    const target = $("#comparison");
    const ids = [Number($("#compare-a").value), Number($("#compare-b").value)];
    if (!ids[0] || !ids[1] || ids[0] === ids[1]) {
      target.innerHTML = `<div class="empty">Choisissez deux dossiers différents.</div>`;
      return;
    }
    try {
      const [a, b] = await Promise.all(ids.map((id) => request(`/api/versions/${id}`)));
      const byCentury = (item) => {
        const grouped = new Map();
        (item.data.timeline || []).forEach((event) => {
          const century = Math.floor((Number(event.year) - 1) / 100) + 1;
          if (!grouped.has(century)) grouped.set(century, []);
          grouped.get(century).push(event);
        });
        return grouped;
      };
      const left = byCentury(a), right = byCentury(b);
      const centuries = [...new Set([...left.keys(), ...right.keys()])].sort((x, y) => x - y);
      target.innerHTML = `<div class="section-head"><h3>${escapeHtml(a.data.query)} <span class="subtle">↔</span> ${escapeHtml(b.data.query)}</h3></div>` +
        (centuries.length ? centuries.map((century) => `<section class="compare-century">
          <div class="compare-side"><ul>${(left.get(century) || []).map((event) =>
            `<li><strong>${escapeHtml(event.year)}</strong> — ${escapeHtml(event.text)}</li>`).join("") || "<li>Pas de repère recensé</li>"}</ul></div>
          <span class="century">${century}<sup>e</sup> siècle</span>
          <div class="compare-side"><ul>${(right.get(century) || []).map((event) =>
            `<li><strong>${escapeHtml(event.year)}</strong> — ${escapeHtml(event.text)}</li>`).join("") || "<li>Pas de repère recensé</li>"}</ul></div>
        </section>`).join("") : `<div class="empty">Ces dossiers n’ont pas encore de repères datés à comparer.</div>`);
    } catch (error) { target.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`; }
  });

  function filename(extension) {
    const name = (current?.data.query || "dossier").normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    return `${name || "dossier"}-historique.${extension}`;
  }

  function download(content, name, mime) {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([content], { type: mime }));
    link.download = name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }

  function exportMarkdown() {
    collectNotes();
    const data = current.data;
    const lines = [`# ${data.page?.title || data.query}`, "", `Recherche : ${data.query}`, "",
      "## Sources documentaires", ...(data.sources || []).map((source) => `- [${source.name}](${source.url}) — ${source.type}`),
      "", "## Repères chronologiques", ...(data.timeline || []).map((event) => `- **${event.year}** — ${event.text} [Source](${event.source})`),
      "", "## Personnalités", ...(data.people || []).map((person) => `- ${person.name} — ${person.detail} [Wikidata](${person.source})`),
      "", "## Lieux à découvrir", ...(data.places || []).map((place) => `- **${place.category || "à vérifier"}** — ${place.name} (${place.detail})`),
      "", "## Traces disparues", ...(data.traces || []).map((trace) => `- ${trace}`),
      "", "## Questions ouvertes", ...(data.questions || []).map((question) => `- ${question}`),
      "", "> Les pistes historiques sont à vérifier auprès des sources citées."];
    download(lines.join("\n"), filename("md"), "text/markdown;charset=utf-8");
  }

  function exportHtml() {
    collectNotes();
    const data = current.data;
    const page = data.page || {};
    const sources = (data.sources || []).map((source) =>
      `<li><a href="${escapeHtml(safeUrl(source.url))}">${escapeHtml(source.name)}</a> — ${escapeHtml(source.type)}</li>`).join("");
    const events = (data.timeline || []).map((event) =>
      `<li><strong>${escapeHtml(event.year)}</strong> — ${escapeHtml(event.text)} <a href="${escapeHtml(safeUrl(event.source))}">Source</a></li>`).join("");
    const people = (data.people || []).map((person) =>
      `<li>${escapeHtml(person.name)} — ${escapeHtml(person.detail)}</li>`).join("");
    const places = (data.places || []).map((place) =>
      `<li>${escapeHtml(place.name)} — ${escapeHtml(place.category || "à vérifier")}</li>`).join("");
    const list = (title, items) => `<h2>${title}</h2><ul>${items || "<li>À compléter</li>"}</ul>`;
    const output = `<!doctype html><html lang="fr"><meta charset="utf-8"><title>${escapeHtml(page.title || data.query)}</title>
      <body><h1>${escapeHtml(page.title || data.query)}</h1><p>Dossier Mnémosyne · ${escapeHtml(data.query)}</p>
      <p>Les éléments ci-dessous sont des pistes à vérifier auprès des sources.</p>
      ${list("Sources documentaires", sources)}${list("Repères chronologiques", events)}
      ${list("Personnalités", people)}${list("Lieux à découvrir", places)}
      ${list("Traces disparues", (data.traces || []).map((item) => `<li>${escapeHtml(item)}</li>`).join(""))}
      ${list("Questions ouvertes", (data.questions || []).map((item) => `<li>${escapeHtml(item)}</li>`).join(""))}
      </body></html>`;
    download(output, filename("html"), "text/html;charset=utf-8");
  }

  loadArchives();
})();
