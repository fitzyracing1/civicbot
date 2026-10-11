// Global directory page: loads data/directory/index.json, then per-continent shards on demand. No third-party calls.
(function () {
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const safeUrl = u => /^https?:\/\//i.test(String(u || "")) ? esc(u) : "#";
  const PER = 48;
  let IDX = null, cont = "", page = 0;
  const shards = {};  // continent -> apis[]

  function loadShard(s) {
    if (shards[s.continent]) return Promise.resolve(shards[s.continent]);
    return fetch("data/directory/" + s.file).then(r => r.json()).then(d => (shards[s.continent] = d.apis));
  }
  function current() {
    const list = cont ? IDX.shards.filter(s => s.continent === cont) : IDX.shards;
    return Promise.all(list.map(loadShard)).then(parts => [].concat(...parts));
  }
  function fillSelect(sel, values, label) {
    const keep = sel.value;
    sel.innerHTML = `<option value="">${label}</option>` + values.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join("");
    if (values.some(([v]) => v === keep)) sel.value = keep;
  }
  function refreshCountries() {
    const cs = Object.entries(IDX.by_country).filter(([, d]) => !cont || d.continent === cont)
      .sort((a, b) => a[1].name.localeCompare(b[1].name)).map(([cc, d]) => [cc, `${d.name} (${d.count})`]);
    fillSelect($("country"), cs, "All countries");
  }
  function render() {
    current().then(rows => {
      const q = $("q").value.trim().toLowerCase(), cc = $("country").value, cat = $("cat").value, auth = $("auth").value,
        kind = $("kind").value, tier = $("tier").value, cors = $("cors").checked;
      const hit = rows.filter(a => a.last_status === "ok" && (!cc || a.country === cc) && (!cat || a.category === cat)
        && (!auth || a.auth === auth) && (!kind || a.kind === kind) && (!tier || a.tier === tier) && (!cors || a.cors)
        && (!q || (a.name + " " + (a.answers || "") + " " + (a.region || "") + " " + (a.city || "") + " " + a.id + " " + a.category).toLowerCase().includes(q)));
      const pages = Math.max(1, Math.ceil(hit.length / PER));
      page = Math.min(page, pages - 1);
      $("count").textContent = `${hit.length.toLocaleString()} match${hit.length === 1 ? "" : "es"}`;
      $("page").textContent = `page ${page + 1} of ${pages}`;
      $("prev").disabled = page === 0; $("next").disabled = page >= pages - 1;
      $("list").innerHTML = hit.slice(page * PER, page * PER + PER).map(a => `<div class="card api">
        <h3><a href="${safeUrl(a.docs || a.example)}" rel="noopener nofollow">${esc(a.name)}</a></h3>
        <span class="pill">${esc(a.category)}</span>
        <span class="pill ${a.auth === "none" ? "ok" : "key"}">${a.auth === "none" ? "no key" : esc(a.auth.replace("-", " "))}</span>
        <span class="pill">${esc(a.kind)}</span>${a.tier === "docs" ? '<span class="pill">docs only</span>' : '<span class="pill ok">endpoint</span>'}
        ${a.cors ? '<span class="pill ok">CORS</span>' : ""}
        <p>${esc(a.answers || "")}</p>
        <p class="meta">${esc([a.city, a.country_name || a.region].filter(Boolean).join(", ") || a.continent)}</p>
        <p class="meta"><code>${esc(a.example)}</code></p>
        <p class="meta">checked ${esc(a.verified && a.verified.date)} · HTTP ${esc(a.verified && a.verified.http)} · ${esc(a.verified && a.verified.mode)}
        ${a.redirects ? " · redirects to " + esc(a.resolved) : ""} · source: ${esc((IDX.sources[a.source] || {}).name || a.source)}</p>
        ${window.grokBar ? window.grokBar(a) : ""}
      </div>`).join("");
    });
  }
  function regions() {
    const items = [["", `All (${IDX.ok.toLocaleString()})`]].concat(
      Object.entries(IDX.by_continent).map(([c, n]) => [c, `${c} (${n.toLocaleString()})`]));
    $("regions").innerHTML = items.map(([c, t]) => `<button data-c="${esc(c)}" aria-pressed="${c === cont}">${esc(t)}</button>`).join("");
  }
  fetch("data/directory/index.json").then(r => r.json()).then(d => {
    IDX = d;
    $("summary").textContent = `${d.ok.toLocaleString()} free APIs and open feeds from ${Object.keys(d.by_country).length} countries ` +
      `and every continent: ${d.endpoint_verified.toLocaleString()} with a working example endpoint and ` +
      `${d.docs_only.toLocaleString()} with reachable docs. Checked ${d.generated}.`;
    fillSelect($("cat"), Object.entries(d.by_category).map(([c, n]) => [c, `${c} (${n})`]), "All categories");
    fillSelect($("kind"), Object.entries(d.by_kind).map(([k, n]) => [k, `${k} (${n})`]), "Any kind");
    regions(); refreshCountries(); render();
  }).catch(() => { $("summary").textContent = "Could not load the directory index."; });
  $("regions").addEventListener("click", e => {
    const b = e.target.closest("button[data-c]"); if (!b) return;
    cont = b.dataset.c; page = 0; regions(); refreshCountries(); render();
  });
  ["q", "country", "cat", "auth", "kind", "tier", "cors"].forEach(id => $(id).addEventListener("input", () => { page = 0; render(); }));
  $("prev").addEventListener("click", () => { page--; render(); window.scrollTo(0, 0); });
  $("next").addEventListener("click", () => { page++; render(); window.scrollTo(0, 0); });
})();
