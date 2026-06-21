/* VN Tech Digest — static reader (filterable, sortable table). */
(function () {
  "use strict";

  const sb = window.supabase.createClient(
    window.SUPABASE_URL,
    window.SUPABASE_ANON_KEY
  );

  const TODAY_WINDOW_HOURS = 48;   // reading horizon for the "Hôm nay" view

  const el = (id) => document.getElementById(id);
  const loginScreen = el("login");
  const appScreen = el("app");
  const feedEl = el("feed");
  const emptyEl = el("empty");
  const loadingEl = el("loading");

  const state = {
    view: "today",            // 'today' | 'archive'
    items: [],                // items loaded for the current view
    statuses: new Map(),      // url -> 'read'|'skipped'|'saved'
    lastVisitAt: null,
    hideRead: false,
    userId: null,
    search: "",
    hiddenSources: new Set(), // sources toggled OFF
    sort: { key: null, dir: "desc" }, // key: 'source'|'score'|'time'|null
  };

  /* ---------- Auth ---------- */

  async function init() {
    const { data } = await sb.auth.getSession();
    if (data.session) onLogin(data.session);
    else { show(loginScreen); hide(appScreen); }
    sb.auth.onAuthStateChange((_e, session) => { if (session) onLogin(session); });
  }

  el("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    el("login-error").textContent = "";
    const { error } = await sb.auth.signInWithPassword({
      email: el("email").value.trim(),
      password: el("password").value,
    });
    if (error) el("login-error").textContent = error.message;
  });

  el("logout").addEventListener("click", async () => {
    await sb.auth.signOut();
    location.reload();
  });

  async function onLogin(session) {
    state.userId = session.user.id;
    hide(loginScreen);
    show(appScreen);
    await loadAndRender();
  }

  /* ---------- Data ---------- */

  async function loadAndRender() {
    show(loadingEl);
    hide(emptyEl);

    const { data: stateRow } = await sb
      .from("user_state").select("last_visit_at")
      .eq("user_id", state.userId).maybeSingle();
    state.lastVisitAt = stateRow ? stateRow.last_visit_at : null;

    let q = sb.from("items").select("*");
    if (state.view === "today") {
      const since = new Date(Date.now() - TODAY_WINDOW_HOURS * 3600e3).toISOString();
      // include dateless items (e.g. spiderum) so they aren't dropped.
      q = q.or(`published_at.gte.${since},published_at.is.null`)
           .order("source", { ascending: true })
           .order("rank_position", { ascending: true });
    } else {
      q = q.order("published_at", { ascending: false, nullsFirst: false }).limit(300);
    }
    const { data: items, error } = await q;
    if (error) console.error(error);
    state.items = items || [];

    state.statuses.clear();
    const urls = state.items.map((i) => i.url);
    if (urls.length) {
      const { data: rows } = await sb
        .from("item_status").select("item_url,status").in("item_url", urls);
      (rows || []).forEach((r) => state.statuses.set(r.item_url, r.status));
    }

    buildSourceChips();
    render();
    hide(loadingEl);

    await sb.from("user_state")
      .upsert({ user_id: state.userId, last_visit_at: new Date().toISOString() });
  }

  /* ---------- Filters ---------- */

  function sourcesInData() {
    const counts = new Map();
    for (const it of state.items) counts.set(it.source, (counts.get(it.source) || 0) + 1);
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }

  function buildSourceChips() {
    const box = el("source-filters");
    box.innerHTML = "";
    for (const [src, n] of sourcesInData()) {
      const b = document.createElement("button");
      b.className = "chip" + (state.hiddenSources.has(src) ? "" : " active");
      b.dataset.source = src;
      b.innerHTML = `${escapeHtml(src)} <span class="n">${n}</span>`;
      b.addEventListener("click", () => {
        if (state.hiddenSources.has(src)) state.hiddenSources.delete(src);
        else state.hiddenSources.add(src);
        b.classList.toggle("active");
        render();
      });
      box.appendChild(b);
    }
  }

  el("chips-all").addEventListener("click", () => {
    state.hiddenSources.clear();
    buildSourceChips();
    render();
  });

  let searchTimer;
  el("search").addEventListener("input", (e) => {
    state.search = e.target.value.trim().toLowerCase();
    clearTimeout(searchTimer);
    searchTimer = setTimeout(render, 150);
  });

  el("hide-read").addEventListener("change", (e) => {
    state.hideRead = e.target.checked;
    render();
  });

  document.querySelectorAll(".views button").forEach((b) => {
    b.addEventListener("click", () => {
      document.querySelectorAll(".views button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      state.view = b.dataset.view;
      loadAndRender();
    });
  });

  /* ---------- Helpers ---------- */

  function isDone(url) {
    const s = state.statuses.get(url);
    return s === "read" || s === "skipped";
  }
  function isNew(item) {
    if (!state.lastVisitAt || !item.published_at) return false;
    return new Date(item.published_at) > new Date(state.lastVisitAt);
  }
  function engagement(item) {
    // value used for the "score" sort: trending gain if present, else total.
    if (item.score_delta != null) return item.score_delta;
    return item.score != null ? item.score : -1;
  }
  function relTime(iso) {
    if (!iso) return "—";
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return "vừa xong";
    if (diff < 3600) return Math.floor(diff / 60) + "m";
    if (diff < 86400) return Math.floor(diff / 3600) + "h";
    const d = Math.floor(diff / 86400);
    return d < 30 ? d + "d" : Math.floor(d / 30) + "mo";
  }
  function compact(n) {
    return n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, "") + "k" : String(n);
  }
  function scoreCell(item) {
    if (item.score == null) return '<span class="muted">—</span>';
    const icon = { comments: "💬", upvotes: "▲", views: "👁",
                   replies_views: "👁", replies: "💬", points: "✦" }[item.score_type] || "•";
    let out = `<span class="score">${icon} ${compact(item.score)}</span>`;
    if (item.score_delta != null && item.score_delta > 0)
      out += ` <span class="trending">🔥 +${compact(item.score_delta)}</span>`;
    return out;
  }

  /* ---------- Render (table) ---------- */

  function applyFilters() {
    let rows = state.items.filter((it) => !state.hiddenSources.has(it.source));
    if (state.hideRead) rows = rows.filter((it) => !isDone(it.url));
    if (state.search) rows = rows.filter((it) => (it.title || "").toLowerCase().includes(state.search));
    const { key, dir } = state.sort;
    if (key) {
      const sign = dir === "asc" ? 1 : -1;
      rows = [...rows].sort((a, b) => {
        let av, bv;
        if (key === "source") { av = a.source; bv = b.source; }
        else if (key === "time") { av = a.published_at || ""; bv = b.published_at || ""; }
        else { av = engagement(a); bv = engagement(b); }
        if (av < bv) return -1 * sign;
        if (av > bv) return 1 * sign;
        return (a.rank_position || 0) - (b.rank_position || 0);
      });
    }
    return rows;
  }

  function sortHeader(label, key) {
    const active = state.sort.key === key;
    const arrow = active ? (state.sort.dir === "asc" ? " ▲" : " ▼") : "";
    return `<th class="sortable${active ? " active" : ""}" data-key="${key}">${label}${arrow}</th>`;
  }

  function render() {
    const rows = applyFilters();
    feedEl.innerHTML = "";

    if (!rows.length) {
      show(emptyEl);
      el("counts").textContent = `${state.items.length} bài`;
      return;
    }
    hide(emptyEl);

    const table = document.createElement("table");
    table.className = "digest";
    table.innerHTML = `
      <thead><tr>
        ${sortHeader("Nguồn", "source")}
        <th>Tiêu đề</th>
        ${sortHeader("Tương tác", "score")}
        ${sortHeader("Thời gian", "time")}
        <th class="actions-col">Triage</th>
      </tr></thead>
      <tbody></tbody>`;
    const tbody = table.querySelector("tbody");
    for (const it of rows) tbody.appendChild(rowEl(it));
    feedEl.appendChild(table);

    table.querySelectorAll("th.sortable").forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.dataset.key;
        if (state.sort.key === key) state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
        else state.sort = { key, dir: key === "source" ? "asc" : "desc" };
        render();
      });
    });

    el("counts").textContent = `${rows.length}/${state.items.length} bài`;
  }

  function rowEl(item) {
    const status = state.statuses.get(item.url) || null;
    const tr = document.createElement("tr");
    tr.className = (isDone(item.url) ? "done " : "") + (isNew(item) ? "is-new" : "");

    const labelClass = (item.rank_label || "").toLowerCase();
    tr.innerHTML = `
      <td class="src">
        <span class="src-name">${escapeHtml(item.source)}</span>
        <span class="label ${labelClass}">${escapeHtml(item.rank_label || "")}</span>
      </td>
      <td class="title">
        ${isNew(item) ? '<span class="badge new">mới</span> ' : ""}
        <a href="${escapeAttr(item.url)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>
        <div class="sub muted">${escapeHtml(item.source_detail || "")}</div>
      </td>
      <td class="score-cell">${scoreCell(item)}</td>
      <td class="time">${relTime(item.published_at)}</td>
      <td class="actions">
        <button data-status="read"    class="${status === "read" ? "active" : ""}" title="Đã đọc">✓</button>
        <button data-status="saved"   class="${status === "saved" ? "active" : ""}" title="Lưu">★</button>
        <button data-status="skipped" class="${status === "skipped" ? "active" : ""}" title="Bỏ qua">✕</button>
      </td>`;

    tr.querySelector(".title a").addEventListener("click", () => setStatus(item.url, "read"));
    tr.querySelectorAll(".actions button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const next = btn.dataset.status;
        const cur = state.statuses.get(item.url);
        setStatus(item.url, cur === next ? null : next);
      });
    });
    return tr;
  }

  /* ---------- Triage writes ---------- */

  async function setStatus(url, status) {
    if (status === null) {
      state.statuses.delete(url);
      await sb.from("item_status").delete()
        .eq("user_id", state.userId).eq("item_url", url);
    } else {
      state.statuses.set(url, status);
      await sb.from("item_status").upsert({
        user_id: state.userId, item_url: url,
        status, updated_at: new Date().toISOString(),
      });
    }
    render();
  }

  el("mark-all").addEventListener("click", async () => {
    const targets = applyFilters().filter((it) => !isDone(it.url));
    if (!targets.length) return;
    const rows = targets.map((it) => ({
      user_id: state.userId, item_url: it.url,
      status: "read", updated_at: new Date().toISOString(),
    }));
    targets.forEach((it) => state.statuses.set(it.url, "read"));
    render();
    await sb.from("item_status").upsert(rows);
  });

  /* ---------- escaping ---------- */
  function show(n) { n.classList.remove("hidden"); }
  function hide(n) { n.classList.add("hidden"); }
  function escapeHtml(s) {
    return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }
  function escapeAttr(s) {
    return String(s).replace(/["&<>]/g, (c) => ({ '"': "&quot;", "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }

  init();
})();
