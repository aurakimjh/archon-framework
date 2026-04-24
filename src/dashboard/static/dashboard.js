/* Archon Dashboard — fetch + WebSocket */
(function () {
  const API = window.location.origin;
  let ws = null;

  async function fetchJSON(path) {
    const r = await fetch(`${API}${path}`);
    return r.ok ? r.json() : null;
  }

  function el(id) { return document.getElementById(id); }

  function badge(decision) {
    const map = {
      AUTO_PASS: "pass", L1_REWORK: "rework",
      L2_HUMAN: "human", L3_HALT: "halt", L4_DEPLOY: "pass"
    };
    return `<span class="badge ${map[decision] || ""}">${decision}</span>`;
  }

  function dot(status) {
    const cls = status === "healthy" ? "healthy"
      : status === "degraded" ? "degraded" : "unhealthy";
    return `<span class="status-dot ${cls}"></span>`;
  }

  /* --- Projects --- */
  async function loadProjects() {
    const data = await fetchJSON("/api/projects");
    if (!data) return;
    el("project-count").textContent = data.length;
    const tbody = el("projects-body");
    tbody.innerHTML = data.map(p => `<tr>
      <td>${p.project_id}</td>
      <td>${p.project_name || "-"}</td>
      <td>${p.status}</td>
      <td>${p.priority}</td>
    </tr>`).join("");
  }

  /* --- Agents --- */
  async function loadAgents() {
    const data = await fetchJSON("/api/agents");
    if (!data) return;
    el("agent-count").textContent = data.length;
    const tbody = el("agents-body");
    tbody.innerHTML = data.map(a => `<tr>
      <td>${dot(a.health_status)}${a.role}</td>
      <td>${a.health_status}</td>
      <td>${a.consecutive_failures}</td>
      <td>${a.avg_latency_ms.toFixed(0)} ms</td>
    </tr>`).join("");
  }

  /* --- Cost --- */
  async function loadCost() {
    const data = await fetchJSON("/api/cost");
    if (!data || !data.length) return;
    const total = data.reduce((s, c) => s + c.total_cost_usd, 0);
    el("total-cost").textContent = `$${total.toFixed(2)}`;
  }

  /* --- Gate Queue --- */
  async function loadGates() {
    const data = await fetchJSON("/api/gates/queue");
    if (!data) return;
    el("gate-count").textContent = data.length;
    const tbody = el("gates-body");
    tbody.innerHTML = data.map(g => `<tr>
      <td>${g.handoff_id.substring(0, 8)}</td>
      <td>${g.project_id}</td>
      <td>${badge(g.gate_level)}</td>
      <td>${g.agent_role}</td>
      <td>
        <button onclick="approveGate('${g.handoff_id}')">Approve</button>
        <button onclick="rejectGate('${g.handoff_id}')">Reject</button>
      </td>
    </tr>`).join("");
  }

  /* --- Metrics --- */
  async function loadMetrics() {
    const data = await fetchJSON("/api/metrics");
    if (!data || !data.total_executions) return;
    el("success-rate").textContent = `${(data.success_rate * 100).toFixed(0)}%`;
  }

  /* --- Gate Actions --- */
  window.approveGate = async function (id) {
    await fetch(`${API}/api/gates/${id}/approve`, { method: "POST" });
    loadGates();
  };
  window.rejectGate = async function (id) {
    await fetch(`${API}/api/gates/${id}/reject`, { method: "POST" });
    loadGates();
  };

  /* --- WebSocket --- */
  function connectWS() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws`);
    ws.onmessage = (e) => {
      const evt = JSON.parse(e.data);
      addEventLog(evt);
      refresh();
    };
    ws.onclose = () => setTimeout(connectWS, 3000);
  }

  function addEventLog(evt) {
    const log = el("events-log");
    if (!log) return;
    const now = new Date().toLocaleTimeString();
    const div = document.createElement("div");
    div.className = "event-line";
    div.innerHTML = `<span class="time">${now}</span> ${evt.event_type}: ${JSON.stringify(evt.payload)}`;
    log.prepend(div);
    while (log.children.length > 50) log.removeChild(log.lastChild);
  }

  /* --- Refresh --- */
  async function refresh() {
    await Promise.all([loadProjects(), loadAgents(), loadCost(), loadGates(), loadMetrics()]);
  }

  document.addEventListener("DOMContentLoaded", () => {
    refresh();
    setInterval(refresh, 15000);
    try { connectWS(); } catch (_) { /* ws optional */ }
  });
})();
