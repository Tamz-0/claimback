// Report form: category attributes, hidden-detail prompts, campus map picker, photo previews.
(function () {
  const cats = JSON.parse(document.getElementById("category-data").textContent);
  const locs = JSON.parse(document.getElementById("location-data").textContent);
  const catSelect = document.getElementById("id_category");
  const locSelect = document.getElementById("id_location");
  const attrBox = document.getElementById("attr-fields");
  const areaSelect = document.getElementById("area-select");

  // ---- Category attributes + suggested private questions --------------------
  function renderCategory() {
    const data = cats[catSelect.value];
    attrBox.innerHTML = "";
    if (!data) return;
    data.attributes.forEach((attr) => {
      const wrap = document.createElement("div");
      wrap.className = "field";
      const id = "attr_" + attr;
      wrap.innerHTML = `<label for="${id}">${attr.charAt(0).toUpperCase() + attr.slice(1)}</label>`;
      const input = document.createElement("input");
      input.type = "text"; input.name = id; input.id = id; input.maxLength = 60;
      wrap.appendChild(input);
      attrBox.appendChild(wrap);
    });
    // Fill empty private-question boxes with the category's suggestions
    const qInputs = document.querySelectorAll("input[data-pq]");
    qInputs.forEach((inp, i) => {
      if (!inp.value || inp.dataset.suggested === "1") {
        inp.value = data.prompts[i] || "";
        inp.dataset.suggested = data.prompts[i] ? "1" : "";
      }
    });
  }
  document.querySelectorAll("input[data-pq]").forEach((inp) =>
    inp.addEventListener("input", () => (inp.dataset.suggested = ""))
  );
  catSelect.addEventListener("change", renderCategory);
  renderCategory();

  // ---- Campus map picker -------------------------------------------------------
  const buildings = locs.filter((l) => l.kind === "building" && l.x !== null);
  const W = 400, H = 260;
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Campus map – tap a building");
  svg.innerHTML = `
    <rect width="${W}" height="${H}" fill="#dcebd8"/>
    <path d="M0 ${H * 0.62} C ${W * 0.3} ${H * 0.55}, ${W * 0.6} ${H * 0.7}, ${W} ${H * 0.6}" stroke="#f3efe3" stroke-width="14" fill="none"/>
    <path d="M${W * 0.5} ${H} L ${W * 0.5} 0" stroke="#f3efe3" stroke-width="10" fill="none"/>
    <circle cx="${W * 0.45}" cy="${H * 0.42}" r="22" fill="#c8e0c2"/>`;
  const pins = {};
  buildings.forEach((b) => {
    const g = document.createElementNS(svgNS, "g");
    g.setAttribute("class", "map-pin");
    g.setAttribute("tabindex", "0");
    const cx = (b.x / 100) * W, cy = (b.y / 100) * H;
    g.innerHTML = `<rect x="${cx - 16}" y="${cy - 11}" width="32" height="22" rx="4" fill="#b9c7b3" opacity=".6"/>
      <circle cx="${cx}" cy="${cy}" r="7"/><text x="${cx}" y="${cy - 12}" text-anchor="middle">${b.name}</text>`;
    g.addEventListener("click", () => chooseBuilding(b.id));
    g.addEventListener("keydown", (e) => { if (e.key === "Enter") chooseBuilding(b.id); });
    svg.appendChild(g);
    pins[b.id] = g;
  });
  document.getElementById("map").appendChild(svg);

  function chooseBuilding(id, keepArea) {
    Object.values(pins).forEach((p) => p.classList.remove("on"));
    if (pins[id]) pins[id].classList.add("on");
    const areas = locs.filter((l) => l.parent === id);
    areaSelect.innerHTML = "";
    const b = locs.find((l) => l.id === id);
    areaSelect.add(new Option(`${b.name} – anywhere`, id));
    areas.forEach((a) => areaSelect.add(new Option(a.name, a.id)));
    areaSelect.style.display = areas.length ? "block" : "none";
    if (!keepArea) { areaSelect.value = id; locSelect.value = id; }
  }
  areaSelect.addEventListener("change", () => (locSelect.value = areaSelect.value));
  locSelect.addEventListener("change", () => {
    const chosen = locs.find((l) => String(l.id) === locSelect.value);
    if (!chosen) return;
    const building = chosen.kind === "building" ? chosen : locs.find((l) => l.id === chosen.parent);
    if (building) { chooseBuilding(building.id, true); areaSelect.value = chosen.id; }
  });
  if (locSelect.value) locSelect.dispatchEvent(new Event("change"));

  // ---- Photo previews ---------------------------------------------------------
  const photoInput = document.getElementById("photo-input");
  const previews = document.getElementById("photo-previews");
  photoInput.addEventListener("change", () => {
    previews.innerHTML = "";
    Array.from(photoInput.files).slice(0, 4).forEach((f) => {
      const img = document.createElement("img");
      img.className = "thumb";
      img.src = URL.createObjectURL(f);
      previews.appendChild(img);
    });
  });
})();
