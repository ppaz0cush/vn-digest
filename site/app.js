/* VN Tech Digest — static reader. Vanilla JS + supabase-js (CDN). */
(function () {
  "use strict";

  const sb = window.supabase.createClient(
    window.SUPABASE_URL,
    window.SUPABASE_ANON_KEY
  );

  const TODAY_WINDOW_HOURS = 48;

  const el = (id) => document.getElementById(id);
  const loginScreen = el("login");
  const appScreen = el("app");
  const feedEl = el("feed");
  const emptyEl = el("empty");
  const loadingEl = el("loading");

  // In-memory state for the current render.
  const state = {
    view: "today",          // 'today' | 'archive'
    items: [],              // items for the current view
    statuses: new Map(),    // url -> 'read'|'skipped'|'saved'
    lastVisitAt: null,      // ISO string of previous visit
    hideRead: false,
    userId: null,
    search: "",
  };

  /* ---------- Auth ---------- */

  async function init() {
    const { data } = await sb.auth.getSession();
    if (data.session) {
      onLogin(data.session);
    } else {
      show(loginScreen);
      hide(appScreen);
    }
    sb.auth.onAuthStateChange((_event, session) => {
      if (session) onLogin(session);
    });
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

    // 1) read last_visit_at (for the "new" badge) BEFORE updating it.
    const { data: stateRow } = await sb
      .from("user_state").select("last_visit_at")
      .eq("user_id", state.userId).maybeSingle();
    state.lastVisitAt = stateRow ? stateRow.last_visit_at : null;

    // 2) items for the current view.
    let q = sb.from("items").select("*");
    if (state.view === "today") {
      const since = new Date(Date.now() - TODAY_WINDOW_HOURS * 3600e3).toISOString();
      q = q.gte("published_at", since)
           .order("source", { ascending: true })
           .order("rank_position", { ascending: true });
    } else {
      if (state.search) q = q.ilike("title", `%${state.search}%`);
      q = q.order("published_at", { ascending: false, nullsFirst: false }).limit(200);
    }
    const { data: items, error } = await q;
    if (error) { console.error(error); }
    state.items = items || [];

    // 3) this user's statuses for the loaded items.
    state.statuses.clear();
    const urls = state.items.map((i) => i.url);
    if (urls.length) {
      const { data: rows } = await sb
        .from("item_status").select("item_url,status")
        .in("item_url", urls);
      (rows || []).forEach((r) => state.statuses.set(r.item_url, r.status));
    }

    render();
    hide(loadingEl);

    // 4) bump last_visit_at to now (after computing "new").
    await sb.from("user_state")
      .upsert({ user_id: state.userId, last_visit_at: new Date().toISOString() });
  }

  /* ---------- Render ---------- */

  function isDone(url) {
    const s = state.statuses.get(url);
    return s === "read" || s === "skipped";
  }
  function isNew(item) {
    if (!state.lastVisitAt || !item.published_at) return false;
    return new Date(item.published_at) > new Date(state.lastVisitAt);
  }

  function relTime(iso) {
    if (!iso) return "";
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

  function scoreBadge(item) {
    if (item.score == null) return "";
    const icon = { comments: "💬", upvotes: "▲", upvote: "▲", views: "👁",
                   replies_views: "👁", views_: "👁", replies: "💬", points: "✦" }[item.score_type] || "•";
    // Cumulative total (muted), plus a "trending" badge showing the gain since
    // the last fetch when we have it.
    let out = `<span class="score">${icon} ${compact(item.score)}</span>`;
    if (item.score_delta != null && item.score_delta > 0) {
      out += ` <span class="trending">🔥 +${compact(item.score_delta)} hôm nay</span>`;
    }
    return out;
  }

  function render() {
    feedEl.innerHTML = "";
    let visible = 0, total = state.items.length;

    // group by source, preserving query order
    const groups = [];
    const bySource = new Map();
    for (const it of state.items) {
      if (!bySource.has(it.source)) {
        const g = { source: it.source, label: it.rank_label, items: [] };
        bySource.set(it.source, g);
        groups.push(g);
      }
      bySource.get(it.source).items.push(it);
    }

    for (const g of groups) {
      const cards = g.items.filter((it) => !(state.hideRead && isDone(it.url)));
      if (!cards.length) continue;
      visible += cards.length;

      const header = document.createElement("div");
      header.className = "group-header";
      const labelClass = (g.label || "").toLowerCase();
      header.innerHTML =
        `<span class="src">${escapeHtml(g.source)}</span>` +
        `<span class="label ${labelClass}">${escapeHtml(g.label || "")}</span>`;
      feedEl.appendChild(header);

      for (const it of cards) feedEl.appendChild(card(it));
    }

    el("counts").textContent = total
      ? `${visible}/${total} hiển thị`
      : "";
    if (!visible) { show(emptyEl); } else { hide(emptyEl); }
  }

  function card(item) {
    const status = state.statuses.get(item.url) || null;
    const div = document.createElement("article");
    div.className = "card" + (isDone(item.url) ? " done" : "") + (isNew(item) ? " is-new" : "");
    div.dataset.url = item.url;

    const meta = [
      escapeHtml(item.source_detail || item.source),
      relTime(item.published_at),
    ].filter(Boolean).map((t) => `<span>${t}</span>`).join("");

    div.innerHTML = `
      <h2 class="title"><a href="${escapeAttr(item.url)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a></h2>
      <div class="meta">
        ${isNew(item) ? '<span class="badge new">mới</span>' : ""}
        ${meta}
        ${scoreBadge(item)}
      </div>
      <div class="actions">
        <button data-status="read"    class="${status === "read" ? "active" : ""}">Đã đọc</button>
        <button data-status="saved"   class="${status === "saved" ? "active" : ""}">Lưu</button>
        <button data-status="skipped" class="${status === "skipped" ? "active" : ""}">Bỏ qua</button>
      </div>`;

    // click-through auto-marks read
    div.querySelector(".title a").addEventListener("click", () => setStatus(item.url, "read"));

    // triage buttons (toggle off if same status tapped again)
    div.querySelectorAll(".actions button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const next = btn.dataset.status;
        const cur = state.statuses.get(item.url);
        setStatus(item.url, cur === next ? null : next);
      });
    });
    return div;
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

  /* ---------- Controls ---------- */

  el("hide-read").addEventListener("change", (e) => {
    state.hideRead = e.target.checked;
    render();
  });

  document.querySelectorAll(".views button").forEach((b) => {
    b.addEventListener("click", () => {
      document.querySelectorAll(".views button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      state.view = b.dataset.view;
      el("archive-bar").classList.toggle("hidden", state.view !== "archive");
      loadAndRender();
    });
  });

  let searchTimer;
  el("search").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    state.search = e.target.value.trim();
    searchTimer = setTimeout(loadAndRender, 300);
  });

  el("mark-all").addEventListener("click", async () => {
    const targets = state.items.filter((it) => !isDone(it.url));
    if (!targets.length) return;
    const rows = targets.map((it) => ({
      user_id: state.userId, item_url: it.url,
      status: "read", updated_at: new Date().toISOString(),
    }));
    targets.forEach((it) => state.statuses.set(it.url, "read"));
    render();
    await sb.from("item_status").upsert(rows);
  });

  /* ---------- helpers ---------- */
  function show(node) { node.classList.remove("hidden"); }
  function hide(node) { node.classList.add("hidden"); }
  function escapeHtml(s) {
    return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }
  function escapeAttr(s) {
    return String(s).replace(/["&<>]/g, (c) => ({ '"': "&quot;", "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }

  init();
})();
