const titles = {
  today: ["Today", "Trends, prompts you can edit, Veo clips, a branded reel, then Instagram."],
  prompts: ["Prompts", "Edit the text Veo will see, then save. Regenerate replaces one channel."],
  clips: ["Clips", "Each card is one Veo job. Dry run makes a local title card instead of calling Google."],
  reel: ["Reel", "Stitch the ready clips into one vertical reel and preview it here."],
  post: ["Post", "A saved Instagram session is used first. Challenges show up here instead of crashing."],
  schedule: ["Schedule", "Runs only while this app is open. No Task Scheduler window."],
  health: ["Health", "Keys, the session, ffmpeg, disk, and whether the OpenClaw gateway is up."],
  settings: ["Settings", "Stored on this PC only. Nothing on this page is committed to git."],
  logs: ["Logs", "The same lines the morning job writes."],
};

const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
let state = { run: null, busy: false, dry_run: true, scheduler: {} };
let settings = null;
let view = "today";

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({ ok: false, error: "Bad response" }));
  if (!response.ok && data.ok !== false) data.ok = false;
  if (!response.ok && !data.error) data.error = `Request failed (${response.status})`;
  return data;
}

function post(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

function phaseSteps(run) {
  const phase = run ? run.phase : "";
  const order = ["trends", "prompts", "veo", "brand", "post"];
  const reached = {
    trends: !!run,
    prompts: !!run,
    veo: ["rendering", "clips_ready", "branding", "ready", "posting", "posted", "error"].includes(phase),
    brand: ["clips_ready", "branding", "ready", "posting", "posted"].includes(phase),
    post: ["ready", "posting", "posted"].includes(phase),
  };
  const current = {
    review: "prompts",
    rendering: "veo",
    clips_ready: "brand",
    branding: "brand",
    ready: "post",
    posting: "post",
    posted: "post",
    error: "veo",
  }[phase];
  return order.map((id) => {
    let cls = "";
    if (reached[id] && current !== id) cls = "done";
    if (current === id) cls = phase === "error" && id === "veo" ? "bad" : "on";
    return { id, cls };
  });
}

function statusPill(status) {
  return `<span class="pill ${esc(status)}">${esc(status || "draft")}</span>`;
}

function renderToday() {
  const run = state.run;
  const steps = phaseSteps(run);
  const labels = { trends: "Trends", prompts: "Prompts", veo: "Veo", brand: "Brand", post: "Post" };
  const stepHtml = steps.map((step) => `<div class="step ${step.cls}"><strong>${labels[step.id]}</strong><em>${step.cls === "done" ? "Done" : step.cls ? "Now" : "Waiting"}</em></div>`).join("");
  const trends = (run && run.trends || []).slice(0, 8).map((topic) => `<span class="chip">${esc(topic)}</span>`).join("");
  const prompts = (run && run.prompts || []).map((prompt) => (
    `<div class="prompt"><strong>${esc(prompt.channel)}</strong> ${statusPill(prompt.status)}<p class="muted">${esc(prompt.trend || "")}</p><p>${esc((prompt.prompt || "").slice(0, 180))}</p>${prompt.error ? `<p class="muted">${esc(prompt.error)}</p>` : ""}</div>`
  )).join("") || `<p class="muted">No batch yet. New batch pulls today's trends and writes five channels.</p>`;
  const log = (run && run.log || []).slice(-12).join("\n") || "No log lines yet.";
  return `
    <div class="steps">${stepHtml}</div>
    <div class="row">
      <button class="btn primary" id="act-batch" ${state.busy ? "disabled" : ""}>New batch</button>
      <button class="btn" id="act-render" ${state.busy || !run ? "disabled" : ""}>Render clips</button>
      <button class="btn" id="act-brand" ${state.busy || !run ? "disabled" : ""}>Stitch and brand</button>
      <button class="btn" id="act-post" ${state.busy || !(run && run.reel) ? "disabled" : ""}>Post reel</button>
    </div>
    <div class="grid">
      <section>
        <div class="card">
          <strong>Trends</strong>
          <div class="chips">${trends || '<span class="chip">waiting</span>'}</div>
          ${run && run.trends_note ? `<p class="muted">${esc(run.trends_note)}</p>` : ""}
        </div>
        <div style="height:12px"></div>
        ${prompts}
      </section>
      <section class="card">
        <strong>This run</strong>
        <p class="muted">${run ? esc(run.id) + " · " + esc(run.phase) : "idle"}${run && run.dry_run ? " · dry run" : ""}</p>
        <div class="log">${esc(log)}</div>
      </section>
    </div>`;
}

function renderPrompts() {
  const prompts = (state.run && state.run.prompts) || [];
  if (!prompts.length) return `<p class="muted">Generate a batch on Today first.</p>`;
  return prompts.map((prompt) => `
    <article class="prompt" data-id="${esc(prompt.id)}">
      <strong>${esc(prompt.channel)}</strong> ${statusPill(prompt.status)}
      <label class="field"><span>Veo prompt</span><textarea class="prompt-text">${esc(prompt.prompt)}</textarea></label>
      <label class="field"><span>Caption</span><textarea class="caption-text">${esc(prompt.caption)}</textarea></label>
      ${prompt.error ? `<p class="muted">${esc(prompt.error)}</p>` : ""}
      <button class="btn regen">Regenerate this one</button>
    </article>`).join("") + `<div class="row"><button class="btn primary" id="save-prompts">Save edits</button></div>`;
}

function clipCard(prompt) {
  const poster = prompt.clip ? `/media/posters/${esc(prompt.clip.replace(/\.mp4$/, ".png"))}` : "";
  const video = prompt.clip ? `<video src="/media/clips/${esc(prompt.clip)}" ${poster ? `poster="${poster}"` : ""} preload="none" controls></video>` : "";
  return `<article class="clip"><h3>${esc(prompt.channel)}</h3>${statusPill(prompt.status)}${video}<p>${esc((prompt.prompt || "").slice(0, 140))}</p>${prompt.error ? `<p class="muted">${esc(prompt.error)}</p>` : ""}</article>`;
}

function renderClips() {
  const prompts = (state.run && state.run.prompts) || [];
  if (!prompts.length) return `<p class="muted">No clips yet.</p>`;
  return `<div class="clips">${prompts.map(clipCard).join("")}</div>`;
}

function renderReel() {
  const run = state.run;
  if (!run || !run.reel) return `<p class="muted">Stitch a reel from Today after at least one clip is ready.</p>`;
  const poster = run.poster ? `/media/posters/${esc(run.poster)}` : "";
  return `<div class="reel"><video src="/media/reels/${esc(run.reel)}" ${poster ? `poster="${poster}"` : ""} preload="none" controls></video><p class="muted">${esc(run.reel)}</p></div>`;
}

function renderPost(history) {
  const run = state.run;
  const caption = (run && run.prompts && run.prompts[0] && run.prompts[0].caption) || "";
  const rows = (history || []).slice().reverse().map((item) => `
    <tr>
      <td>${esc(item.at || "")}</td>
      <td>${esc(item.file || "")}${item.dry_run ? " · dry run" : ""}</td>
      <td>${item.url ? `<a href="${esc(item.url)}">${esc(item.url)}</a>` : esc(item.error || (item.ok ? "Saved locally" : ""))}</td>
    </tr>`).join("");
  return `
    <label class="field"><span>Caption for this reel</span><textarea id="post-caption">${esc(caption)}</textarea></label>
    <label class="field"><span>Authenticator code, only if Instagram asks</span><input id="post-code" type="text" inputmode="numeric" autocomplete="one-time-code"></label>
    <div class="row"><button class="btn primary" id="do-post" ${run && run.reel ? "" : "disabled"}>Post now</button></div>
    <h2>History</h2>
    <table><thead><tr><th>When</th><th>File</th><th>Result</th></tr></thead><tbody>${rows || "<tr><td colspan='3' class='muted'>Nothing posted yet.</td></tr>"}</tbody></table>`;
}

function renderSchedule() {
  const sched = (settings && settings.schedule) || { weekdays: [], batch_time: "09:00", post_time: "12:00" };
  const days = dayNames.map((name, index) => `
    <label><input type="checkbox" class="day" value="${index}" ${sched.weekdays.includes(index) ? "checked" : ""}> ${name}</label>`).join("");
  const next = state.scheduler || {};
  return `
    <div class="card">
      <label class="field"><span><input type="checkbox" id="batch-on" ${sched.batch_enabled ? "checked" : ""}> Morning batch</span>
        <input type="time" id="batch-time" value="${esc(sched.batch_time)}"></label>
      <p class="muted">Next: ${esc(next.next_batch || "off")}. Last ran ${esc(next.last_batch_date || "never")}.</p>
      <label class="field"><span><input type="checkbox" id="post-on" ${sched.post_enabled ? "checked" : ""}> Midday post</span>
        <input type="time" id="post-time" value="${esc(sched.post_time)}"></label>
      <p class="muted">Next: ${esc(next.next_post || "off")}. Last ran ${esc(next.last_post_date || "never")}.</p>
      <div class="days">${days}</div>
      <div class="row"><button class="btn primary" id="save-schedule">Save schedule</button></div>
      <p class="muted">Leave this app running. Closing the browser does not stop it. Stop Vidrot.vbs does.</p>
    </div>`;
}

function renderHealth(health) {
  if (!health) return `<p class="muted">Loading…</p>`;
  const cards = [
    ["Veo", health.veo],
    ["Instagram", health.instagram],
    ["OpenClaw", health.openclaw],
    ["ffmpeg", health.ffmpeg],
    ["Disk", health.disk],
    ["Output", health.output],
  ];
  return `<div class="health">${cards.map(([name, card]) => `
    <article class="health-card">
      <h3>${esc(name)} ${card.ok ? '<span class="pill ok">ok</span>' : '<span class="pill bad">check</span>'}</h3>
      <p>${esc(card.detail || "")}</p>
    </article>`).join("")}</div>
    <div class="row">
      <button class="btn" id="test-veo">Test Veo key</button>
      <button class="btn" id="test-ig">Test Instagram login</button>
    </div>
    <p class="muted">${health.last_run ? "Last run " + esc(health.last_run.id) + " is " + esc(health.last_run.phase) + "." : "No run yet."}</p>`;
}

function renderSettings() {
  if (!settings) return `<p class="muted">Loading…</p>`;
  return `
    <p class="muted">Saved at ${esc(settings.data_dir)}</p>
    <label class="field"><span>Gemini API key ${settings.gemini_api_key_set ? "(" + esc(settings.gemini_api_key_mask) + " saved)" : ""}</span>
      <input id="set-key" type="password" placeholder="${settings.gemini_api_key_set ? "Leave blank to keep the saved key" : "From aistudio.google.com"}"></label>
    <label class="field"><span>Veo model</span><input id="set-model" type="text" value="${esc(settings.veo_model)}"></label>
    <label class="field"><span>Clip length (seconds)</span>
      <select id="set-duration">${[4, 6, 8].map((n) => `<option ${Number(settings.veo_duration_seconds) === n ? "selected" : ""}>${n}</option>`).join("")}</select></label>
    <label class="field"><span>Instagram username</span><input id="set-user" type="text" value="${esc(settings.ig_username)}"></label>
    <label class="field"><span>Instagram password ${settings.ig_password_set ? "(saved)" : ""}</span>
      <input id="set-pass" type="password" placeholder="${settings.ig_password_set ? "Leave blank to keep it" : ""}"></label>
    <label class="field"><span>OpenClaw gateway</span><input id="set-claw" type="text" value="${esc(settings.openclaw_url)}"></label>
    <label class="field"><span>Trends country</span><input id="set-geo" type="text" value="${esc(settings.trends_geo)}"></label>
    <label class="field"><span>Batch size</span><input id="set-count" type="number" min="1" max="8" value="${esc(settings.batch_size)}"></label>
    <label class="field"><span>ffmpeg path, if it is not on PATH</span><input id="set-ff" type="text" value="${esc(settings.ffmpeg_path)}"></label>
    <div class="row"><button class="btn primary" id="save-settings">Save settings</button></div>`;
}

function renderLogs(lines) {
  return `<div class="card"><div class="log">${esc((lines || []).join("\n")) || "Log is empty."}</div></div>`;
}

function setBanner(text, ok) {
  const banner = document.getElementById("banner");
  if (!text) {
    banner.hidden = true;
    banner.textContent = "";
    return;
  }
  banner.hidden = false;
  banner.className = ok ? "banner ok" : "banner";
  banner.textContent = text;
}

async function draw() {
  document.getElementById("title").textContent = titles[view][0];
  document.getElementById("subtitle").textContent = titles[view][1];
  document.querySelectorAll("#nav a").forEach((link) => {
    link.classList.toggle("active", link.dataset.view === view);
  });
  const root = document.getElementById("view");
  if (view === "today") root.innerHTML = renderToday();
  else if (view === "prompts") root.innerHTML = renderPrompts();
  else if (view === "clips") root.innerHTML = renderClips();
  else if (view === "reel") root.innerHTML = renderReel();
  else if (view === "post") root.innerHTML = renderPost((await api("/api/history")).posts);
  else if (view === "schedule") root.innerHTML = renderSchedule();
  else if (view === "health") root.innerHTML = renderHealth((await api("/api/health")).health);
  else if (view === "settings") root.innerHTML = renderSettings();
  else if (view === "logs") root.innerHTML = renderLogs((await api("/api/logs")).lines);
  wire();
  const run = state.run;
  const message = run && run.error && view === "today" ? run.error : "";
  setBanner(message, run && run.phase !== "error" && message);
}

function wire() {
  const batch = document.getElementById("act-batch");
  if (batch) batch.onclick = () => act("/api/batch", {});
  const render = document.getElementById("act-render");
  if (render) render.onclick = () => act("/api/render", {});
  const brand = document.getElementById("act-brand");
  if (brand) brand.onclick = () => act("/api/brand", {});
  const postBtn = document.getElementById("act-post");
  if (postBtn) postBtn.onclick = () => { location.hash = "#post"; };
  const save = document.getElementById("save-prompts");
  if (save) save.onclick = savePrompts;
  document.querySelectorAll(".regen").forEach((button) => {
    button.onclick = async () => {
      const id = button.closest(".prompt").dataset.id;
      const result = await post("/api/prompts/regenerate", { id });
      show(result);
      await refresh();
    };
  });
  const doPost = document.getElementById("do-post");
  if (doPost) doPost.onclick = async () => {
    const result = await post("/api/post", {
      caption: document.getElementById("post-caption").value,
      verification_code: document.getElementById("post-code").value,
    });
    show(result);
    await refresh();
  };
  const saveSched = document.getElementById("save-schedule");
  if (saveSched) saveSched.onclick = saveSchedule;
  const testVeo = document.getElementById("test-veo");
  if (testVeo) testVeo.onclick = async () => show(await post("/api/veo/test", {}), true);
  const testIg = document.getElementById("test-ig");
  if (testIg) testIg.onclick = async () => show(await post("/api/instagram/test", {}), true);
  const saveSet = document.getElementById("save-settings");
  if (saveSet) saveSet.onclick = saveSettingsForm;
}

function show(result, preferDetail) {
  if (!result) return;
  if (result.ok === false) setBanner(result.error || result.detail || "Something went wrong.", false);
  else setBanner(preferDetail ? (result.detail || "OK") : (result.error || ""), result.ok !== false);
}

async function act(path, body) {
  const result = await post(path, body);
  show(result);
  await refresh();
}

async function savePrompts() {
  const prompts = [...document.querySelectorAll(".prompt")].map((node) => ({
    id: node.dataset.id,
    prompt: node.querySelector(".prompt-text").value,
    caption: node.querySelector(".caption-text").value,
  }));
  show(await post("/api/prompts", { prompts }));
  await refresh();
}

async function saveSchedule() {
  const weekdays = [...document.querySelectorAll(".day")].filter((box) => box.checked).map((box) => Number(box.value));
  const result = await post("/api/schedule", {
    batch_enabled: document.getElementById("batch-on").checked,
    batch_time: document.getElementById("batch-time").value,
    post_enabled: document.getElementById("post-on").checked,
    post_time: document.getElementById("post-time").value,
    weekdays,
  });
  show(result.error ? result : { ok: true, detail: "Schedule saved." }, true);
  settings = result.settings || settings;
  await refresh();
}

async function saveSettingsForm() {
  const payload = {
    veo_model: document.getElementById("set-model").value,
    veo_duration_seconds: Number(document.getElementById("set-duration").value),
    ig_username: document.getElementById("set-user").value,
    openclaw_url: document.getElementById("set-claw").value,
    trends_geo: document.getElementById("set-geo").value,
    batch_size: Number(document.getElementById("set-count").value),
    ffmpeg_path: document.getElementById("set-ff").value,
  };
  const key = document.getElementById("set-key").value.trim();
  const password = document.getElementById("set-pass").value;
  if (key) payload.gemini_api_key = key;
  if (password) payload.ig_password = password;
  const result = await post("/api/settings", payload);
  show(result.error ? result : { ok: true, detail: "Settings saved on this PC." }, true);
  if (result.settings) settings = result.settings;
  await refresh();
}

let refreshing = false;
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    state = await api("/api/state");
    const foot = document.getElementById("aside-status");
    const phase = state.run ? state.run.phase : "idle";
    foot.textContent = `${state.dry_run ? "Dry run on" : "Live"} · ${state.busy ? "working" : phase}`;
    const dry = document.getElementById("dry-run");
    if (document.activeElement !== dry) dry.checked = !!state.dry_run;
    if (view === "today" || view === "clips" || view === "reel") await draw();
  } finally {
    refreshing = false;
  }
}

function route() {
  view = (location.hash || "#today").slice(1);
  if (!titles[view]) view = "today";
  draw();
}

document.getElementById("dry-run").addEventListener("change", async (event) => {
  const result = await post("/api/settings", { dry_run: event.target.checked });
  if (result.settings) settings = result.settings;
  await refresh();
});

window.addEventListener("hashchange", route);

(async function start() {
  settings = (await api("/api/settings")).settings;
  await refresh();
  route();
  setInterval(refresh, 2000);
})();
