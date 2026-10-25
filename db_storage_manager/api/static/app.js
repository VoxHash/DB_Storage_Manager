(() => {
  const tokenKey = "dsm_api_token";

  function authHeaders() {
    const headers = { Accept: "application/json" };
    const params = new URLSearchParams(window.location.search);
    const fromQuery = params.get("token");
    if (fromQuery) {
      sessionStorage.setItem(tokenKey, fromQuery);
    }
    const token = sessionStorage.getItem(tokenKey) || "";
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    return headers;
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      headers: {
        ...authHeaders(),
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
    });
    const text = await res.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      data = { raw: text };
    }
    if (!res.ok) {
      const err = new Error((data && data.error) || res.statusText);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  function setText(id, value, cls) {
    const el = document.getElementById(id);
    el.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    el.classList.remove("ok", "fail");
    if (cls) el.classList.add(cls);
  }

  async function loadStatus() {
    try {
      const health = await api("/api/v1/health");
      let info = null;
      try {
        info = await api("/api/v1/info");
      } catch (e) {
        info = { note: "info requires auth if DSM_API_TOKEN is set", error: String(e.message) };
      }
      setText("status-out", { health, info }, "ok");
    } catch (e) {
      setText("status-out", { error: e.message, data: e.data }, "fail");
    }
  }

  async function loadConnections() {
    try {
      const data = await api("/api/v1/connections");
      setText("conn-out", data, "ok");
    } catch (e) {
      setText("conn-out", { error: e.message, data: e.data }, "fail");
    }
  }

  let backups = [];

  async function loadBackups() {
    const list = document.getElementById("backup-list");
    list.innerHTML = "";
    try {
      const data = await api("/api/v1/backups");
      backups = data.backups || [];
      if (!backups.length) {
        list.innerHTML = "<li class='meta'>No local backups found.</li>";
        return;
      }
      for (const b of backups) {
        const li = document.createElement("li");
        const id = `b-${b.id}`;
        li.innerHTML = `
          <label for="${id}">
            <input type="radio" name="backup" id="${id}" value="${b.id}" />
            <span>
              <strong>${b.name}</strong>
              <div class="meta">${b.id} · ${b.size} bytes · ${b.createdAt || ""}</div>
            </span>
          </label>`;
        list.appendChild(li);
      }
      setText("backup-action-out", `Loaded ${backups.length} backup(s) from ${data.backup_dir}`);
    } catch (e) {
      setText("backup-action-out", { error: e.message, data: e.data }, "fail");
    }
  }

  function selectedBackupId() {
    const checked = document.querySelector('input[name="backup"]:checked');
    return checked ? checked.value : null;
  }

  async function postAction(kind) {
    const id = selectedBackupId();
    if (!id) {
      setText("backup-action-out", "Select a backup first.", "fail");
      return;
    }
    try {
      const data = await api(`/api/v1/backups/${encodeURIComponent(id)}/${kind}`, {
        method: "POST",
        body: "{}",
      });
      setText("backup-action-out", data, data.ok ? "ok" : "fail");
    } catch (e) {
      setText("backup-action-out", { error: e.message, data: e.data }, "fail");
    }
  }

  document.getElementById("refresh-conn").addEventListener("click", loadConnections);
  document.getElementById("refresh-backups").addEventListener("click", loadBackups);
  document.getElementById("verify-selected").addEventListener("click", () => postAction("verify"));
  document.getElementById("dryrun-selected").addEventListener("click", () => postAction("dry-run"));

  loadStatus();
  loadConnections();
  loadBackups();
})();
