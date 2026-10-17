const titles = {
  today: ["Today", "Trends, prompts, Veo, a reel, then Instagram. The server keeps working if you lock the phone."],
  prompts: ["Prompts", "Edit the text Veo will see, then save. Regenerate replaces one channel."],
  clips: ["Clips", "Each card is one Veo job. Dry run makes a title card instead of calling Google."],
  reel: ["Reel", "The stitched vertical reel. Play it here before you post."],
  post: ["Post", "Uses the saved Instagram session. A checkpoint shows up here for you to approve."],
  schedule: ["Schedule", "Runs on the server. Your phone and PC can both be off."],
  health: ["Health", "Veo key, Instagram session, ffmpeg, disk, and the last job."],
  settings: ["Settings", "Secrets stay on the server, encrypted. Nothing here is committed to git."],
  logs: ["Logs", "The same lines the morning job writes."],
};

const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
let state = { run: null, busy: false, dry_run: true, scheduler: {}, notice: null };
let settings = null;
let view = "today";
let signedIn = false;
let passkeyReady = false;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

async function api(path, options) {
  const opts = options || {};
  opts.headers = Object.assign({ "X-Vidrot-Request": "1" }, opts.headers || {});
  const response = await fetch(path, opts);
  const data = await response.json().catch(() => ({ ok: false, error: "Bad response" }));
  if (response.status === 401) {
    showLogin();
    data.ok = false;
    data.error = data.error || "Sign in required.";
  }
  if (!response.ok && data.ok !== false) data.ok = false;
  if (!response.ok && !data.error) data.error = `Request failed (${response.status})`;
  return data;
}

function post(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Vidrot-Request": "1" },
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
  const stepHtml = steps.map((step) => `<div class="step ${step.cls}"><strong>${labels[step.id]}</strong><em>${step.cls === "done" ? "Done" : step.cls ? "Now" : "Wait"}</em></div>`).join("");
  const trends = (run && run.trends || []).slice(0, 8).map((topic) => `<span class="chip">${esc(topic)}</span>`).join("");
  const prompts = (run && run.prompts || []).map((prompt) => (
    `<div class="prompt"><strong>${esc(prompt.channel)}</strong> ${statusPill(prompt.status)}<p class="muted">${esc(prompt.trend || "")}</p><p>${esc((prompt.prompt || "").slice(0, 180))}</p>${prompt.error ? `<p class="muted">${esc(prompt.error)}</p>` : ""}</div>`
  )).join("") || `<p class="muted">No batch yet. New batch pulls today's trends and writes five channels.</p>`;
  const log = (run && run.log || []).slice(-8).join("\n") || "No log lines yet.";
  return `
    <div class="steps">${stepHtml}</div>
    <div class="row">
      <button class="btn primary" id="act-batch" ${state.busy ? "disabled" : ""}>New batch</button>
      <button class="btn" id="act-render" ${state.busy || !run ? "disabled" : ""}>Render clips</button>
      <button class="btn" id="act-brand" ${state.busy || !run ? "disabled" : ""}>Stitch and brand</button>
      <button class="btn" id="act-post" ${state.busy || !(run && run.reel) ? "disabled" : ""}>Open post</button>
    </div>
    <div class="card">
      <strong>Trends</strong>
      <div class="chips">${trends || '<span class="chip">waiting</span>'}</div>
      ${run && run.trends_note ? `<p class="muted">${esc(run.trends_note)}</p>` : ""}
    </div>
    ${prompts}
    <section class="card">
      <strong>This run</strong>
      <p class="muted">${run ? esc(run.id) + " · " + esc(run.phase) : "idle"}${run && run.dry_run ? " · dry run" : ""}</p>
      <div class="log">${esc(log)}</div>
    </section>`;
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
  const poster = prompt.clip ? `media/posters/${esc(prompt.clip.replace(/\.mp4$/, ".png"))}` : "";
  const still = poster ? `<img class="still" src="${poster}" alt="Preview">` : "";
  const video = prompt.clip ? `<video src="media/clips/${esc(prompt.clip)}" ${poster ? `poster="${poster}"` : ""} preload="none" playsinline controls></video>` : "";
  return `<article class="clip"><h3>${esc(prompt.channel)}</h3>${statusPill(prompt.status)}${still}${video}<p>${esc((prompt.prompt || "").slice(0, 140))}</p>${prompt.error ? `<p class="muted">${esc(prompt.error)}</p>` : ""}</article>`;
}

function renderClips() {
  const prompts = (state.run && state.run.prompts) || [];
  if (!prompts.length) return `<p class="muted">No clips yet.</p>`;
  return `<div class="clips">${prompts.map(clipCard).join("")}</div>`;
}

function renderReel() {
  const run = state.run;
  if (!run || !run.reel) return `<p class="muted">Stitch a reel from Today after at least one clip is ready.</p>`;
  const poster = run.poster ? `media/posters/${esc(run.poster)}` : "";
  return `<div class="reel"><video src="media/reels/${esc(run.reel)}" ${poster ? `poster="${poster}"` : ""} preload="none" playsinline controls></video><p class="muted">${esc(run.reel)}</p></div>`;
}

function renderPost(history) {
  const run = state.run;
  const caption = (run && run.prompts && run.prompts[0] && run.prompts[0].caption) || "";
  const rows = (history || []).slice().reverse().map((item) => `
    <tr>
      <td>${esc((item.at || "").replace("T", " ").slice(0, 16))}</td>
      <td>${esc(item.file || "")}${item.dry_run ? " · dry run" : ""}</td>
      <td>${item.url ? `<a href="${esc(item.url)}">${esc(item.url)}</a>` : esc(item.error || (item.ok ? "Saved locally" : ""))}</td>
    </tr>`).join("");
  const notice = state.notice && state.notice.error ? `<p class="muted">${esc(state.notice.error)}</p>` : "";
  return `
    ${notice}
    <label class="field"><span>Caption for this reel</span><textarea id="post-caption">${esc(caption)}</textarea></label>
    <label class="field"><span>Code, only if Instagram asks</span><input id="post-code" type="text" inputmode="numeric" autocomplete="one-time-code"></label>
    <div class="row">
      <button class="btn primary" id="do-post" ${run && run.reel ? "" : "disabled"}>Post now</button>
      <button class="btn" id="retry-ig" type="button">I approved it — try again</button>
    </div>
    <h2>History</h2>
    <table><thead><tr><th>When</th><th>File</th><th>Result</th></tr></thead><tbody>${rows || "<tr><td colspan='3' class='muted'>Nothing posted yet.</td></tr>"}</tbody></table>`;
}

function renderSchedule() {
  const sched = (settings && settings.schedule) || { weekdays: [], batch_time: "09:00", post_time: "12:00" };
  const zone = (settings && settings.timezone) || (state.scheduler && state.scheduler.timezone) || "UTC";
  const days = dayNames.map((name, index) => `
    <label><input type="checkbox" class="day" value="${index}" ${(sched.weekdays || []).includes(index) ? "checked" : ""}> ${name}</label>`).join("");
  const next = state.scheduler || {};
  return `
    <div class="card">
      <p class="muted">Times use ${esc(zone)}. Change the zone in Settings.</p>
      <label class="field"><span><input type="checkbox" id="batch-on" ${sched.batch_enabled ? "checked" : ""}> Morning batch</span>
        <input type="time" id="batch-time" value="${esc(sched.batch_time)}"></label>
      <p class="muted">Next: ${esc(next.next_batch || "off")}. Last ran ${esc(next.last_batch_date || "never")}.</p>
      <label class="field"><span><input type="checkbox" id="post-on" ${sched.post_enabled ? "checked" : ""}> Midday post</span>
        <input type="time" id="post-time" value="${esc(sched.post_time)}"></label>
      <p class="muted">Next: ${esc(next.next_post || "off")}. Last ran ${esc(next.last_post_date || "never")}.</p>
      <div class="days">${days}</div>
      <div class="row"><button class="btn primary" id="save-schedule">Save schedule</button></div>
      <p class="muted">Leave the server running. Closing this page does not stop the jobs.</p>
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
      <button class="btn" id="enable-alerts">Allow alerts on this phone</button>
    </div>
    <p class="muted">${health.last_run ? "Last run " + esc(health.last_run.id) + " is " + esc(health.last_run.phase) + "." : "No run yet."}</p>`;
}

function renderSettings(passkeys) {
  if (!settings) return `<p class="muted">Loading…</p>`;
  const saved = (passkeys || []).map((item) => `
    <p class="muted">Saved ${esc(item.created_at)}${item.backed_up ? " · synced" : ""}</p>
    <button class="btn" type="button" data-passkey="${esc(item.id)}">Remove passkey</button>`).join("");
  return `
    <div class="card">
      <h2>Passkey</h2>
      <p class="muted">An Apple passkey on this iPhone. Face ID or Touch ID signs you in. The password stays here if you lose the phone.</p>
      ${saved || `<p class="muted">No passkey saved yet.</p>`}
      <div class="row"><button class="btn primary" id="save-passkey" type="button">Save a passkey</button></div>
    </div>
    <p class="muted">Saved on the server at ${esc(settings.data_dir)}. Encrypted. Not in git.</p>
    <label class="field"><span>Gemini API key ${settings.gemini_api_key_set ? "(" + esc(settings.gemini_api_key_mask) + " saved)" : ""}</span>
      <input id="set-key" type="password" autocomplete="off" placeholder="${settings.gemini_api_key_set ? "Leave blank to keep the saved key" : "Or set GEMINI_API_KEY on the host"}"></label>
    <label class="field"><span>Veo model</span><input id="set-model" type="text" value="${esc(settings.veo_model)}"></label>
    <label class="field"><span>Clip length (seconds)</span>
      <select id="set-duration">${[4, 6, 8].map((n) => `<option ${Number(settings.veo_duration_seconds) === n ? "selected" : ""}>${n}</option>`).join("")}</select></label>
    <label class="field"><span>Instagram username</span><input id="set-user" type="text" value="${esc(settings.ig_username)}"></label>
    <label class="field"><span>Instagram password ${settings.ig_password_set ? "(saved)" : ""}</span>
      <input id="set-pass" type="password" autocomplete="new-password" placeholder="${settings.ig_password_set ? "Leave blank to keep it" : ""}"></label>
    <label class="field"><span>Import session.json ${settings.session_saved ? "(a session is saved)" : ""}</span>
      <input id="set-session" type="file" accept="application/json,.json"></label>
    <label class="field"><span>Instagram proxy ${settings.ig_proxy_set ? "(" + esc(settings.ig_proxy_mask) + ")" : "(optional)"}</span>
      <input id="set-proxy" type="text" placeholder="http://user:pass@home-proxy:8080" autocomplete="off"></label>
    <p class="muted">Instagram often flags a datacenter IP. A proxy you control, such as a machine at home, is the mitigation. Leave this blank to post directly.</p>
    <label class="field"><span>Timezone</span><input id="set-tz" type="text" value="${esc(settings.timezone)}"></label>
    <label class="field"><span><input type="checkbox" id="set-claw-on" ${settings.openclaw_enabled ? "checked" : ""}> Check an OpenClaw gateway</span>
      <input id="set-claw" type="text" value="${esc(settings.openclaw_url)}" placeholder="Off unless the PC is on"></label>
    <label class="field"><span>Trends country</span><input id="set-geo" type="text" value="${esc(settings.trends_geo)}"></label>
    <label class="field"><span>Batch size</span><input id="set-count" type="number" min="1" max="8" value="${esc(settings.batch_size)}"></label>
    <label class="field"><span>ffmpeg path, if it is not on PATH</span><input id="set-ff" type="text" value="${esc(settings.ffmpeg_path)}" placeholder="The server image already includes ffmpeg"></label>
    <div class="row"><button class="btn primary" id="save-settings">Save settings</button></div>`;
}

function renderLogs(lines) {
  return `<div class="card"><div class="log">${esc((lines || []).join("\n")) || "Log is empty."}</div></div>`;
}

function setBanner(text, ok) {
  const banner = document.getElementById("banner");
  if (!banner) return;
  if (!text) {
    banner.hidden = true;
    banner.textContent = "";
    return;
  }
  banner.hidden = false;
  banner.className = ok ? "banner ok" : "banner";
  banner.textContent = text;
}

function paintNotice() {
  const node = document.getElementById("notice");
  if (!node) return;
  const text = state.notice && state.notice.error;
  node.hidden = !text;
  node.textContent = text || "";
}

function paintStatus(previous) {
  const el = document.getElementById("job-status");
  if (!el) return;
  const run = state.run;
  const phase = run ? run.phase : "idle";
  let text = "Idle";
  let cls = "job";
  if (state.busy) {
    text = "Working · " + String(phase).replace(/_/g, " ");
    cls = "job busy";
  } else if (phase === "error") {
    text = "Failed · " + (run.error || "open Logs");
    cls = "job bad";
  } else if (run) {
    text = String(phase).replace(/_/g, " ");
    if (run.dry_run) text += " · dry run";
    cls = phase === "posted" || phase === "ready" || phase === "clips_ready" ? "job ok" : "job";
  }
  el.className = cls;
  el.textContent = text;
  maybeNotify(previous, state);
}

function maybeNotify(previous, next) {
  if (!previous || !previous.run || !next || !next.run) return;
  if (previous.run.phase === next.run.phase && previous.busy === next.busy) return;
  const phase = next.run.phase;
  if (!["error", "posted", "ready", "clips_ready"].includes(phase) || next.busy) return;
  const title = phase === "error" ? "vidrot failed" : "vidrot " + phase.replace(/_/g, " ");
  const body = next.run.error || title;
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  try {
    new Notification(title, { body, icon: "icons/icon-192.png" });
  } catch (err) {
    /* the in-app bar still shows the same status */
  }
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
  else if (view === "post") root.innerHTML = renderPost((await api("api/history")).posts);
  else if (view === "schedule") root.innerHTML = renderSchedule();
  else if (view === "health") root.innerHTML = renderHealth((await api("api/health")).health);
  else if (view === "settings") root.innerHTML = renderSettings((await api("api/passkeys")).passkeys || []);
  else if (view === "logs") root.innerHTML = renderLogs((await api("api/logs")).lines);
  wire();
  paintNotice();
  const run = state.run;
  const message = run && run.error && view === "today" ? run.error : "";
  if (message && !(state.notice && state.notice.error)) setBanner(message, run && run.phase !== "error");
}

function wire() {
  const batch = document.getElementById("act-batch");
  if (batch) batch.onclick = () => act("api/batch", {});
  const render = document.getElementById("act-render");
  if (render) render.onclick = () => act("api/render", {});
  const brand = document.getElementById("act-brand");
  if (brand) brand.onclick = () => act("api/brand", {});
  const postBtn = document.getElementById("act-post");
  if (postBtn) postBtn.onclick = () => { location.hash = "#post"; };
  const save = document.getElementById("save-prompts");
  if (save) save.onclick = savePrompts;
  document.querySelectorAll(".regen").forEach((button) => {
    button.onclick = async () => {
      const id = button.closest(".prompt").dataset.id;
      const result = await post("api/prompts/regenerate", { id });
      show(result);
      await refresh();
    };
  });
  const doPost = document.getElementById("do-post");
  if (doPost) doPost.onclick = async () => {
    const result = await post("api/post", {
      caption: document.getElementById("post-caption").value,
      verification_code: document.getElementById("post-code").value,
    });
    show(result);
    await refresh();
  };
  const retry = document.getElementById("retry-ig");
  if (retry) retry.onclick = async () => {
    const code = document.getElementById("post-code").value;
    show(await post("api/instagram/test", { verification_code: code }), true);
    await refresh();
  };
  const saveSched = document.getElementById("save-schedule");
  if (saveSched) saveSched.onclick = saveSchedule;
  const testVeo = document.getElementById("test-veo");
  if (testVeo) testVeo.onclick = async () => show(await post("api/veo/test", {}), true);
  const testIg = document.getElementById("test-ig");
  if (testIg) testIg.onclick = async () => {
    show(await post("api/instagram/test", {}), true);
    await refresh();
  };
  const alerts = document.getElementById("enable-alerts");
  if (alerts) alerts.onclick = enableAlerts;
  const saveSet = document.getElementById("save-settings");
  if (saveSet) saveSet.onclick = saveSettingsForm;
  const sessionFile = document.getElementById("set-session");
  if (sessionFile) sessionFile.onchange = () => importSession(sessionFile.files && sessionFile.files[0]);
  const savePasskey = document.getElementById("save-passkey");
  if (savePasskey) savePasskey.onclick = () => createPasskey();
  document.querySelectorAll("[data-passkey]").forEach((button) => {
    button.onclick = async () => {
      const result = await post("api/passkey/delete", { id: button.dataset.passkey });
      if (!result.ok) {
        setBanner(result.error || "Could not remove that passkey.", false);
        return;
      }
      const session = await api("api/session");
      passkeyReady = !!session.passkey;
      paintPasskey();
      setBanner("Passkey removed.", true);
      if (view === "settings") route();
    };
  });
}

function show(result, preferDetail) {
  if (!result) return;
  if (result.ok === false) setBanner(result.error || result.detail || "Something went wrong.", false);
  else setBanner(preferDetail ? (result.detail || result.error || "OK") : (result.error || ""), result.ok !== false);
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
  show(await post("api/prompts", { prompts }));
  await refresh();
}

async function saveSchedule() {
  const weekdays = [...document.querySelectorAll(".day")].filter((box) => box.checked).map((box) => Number(box.value));
  const result = await post("api/schedule", {
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
    openclaw_enabled: document.getElementById("set-claw-on").checked,
    openclaw_url: document.getElementById("set-claw").value,
    trends_geo: document.getElementById("set-geo").value,
    batch_size: Number(document.getElementById("set-count").value),
    ffmpeg_path: document.getElementById("set-ff").value,
    timezone: document.getElementById("set-tz").value,
  };
  const key = document.getElementById("set-key").value.trim();
  const password = document.getElementById("set-pass").value;
  const proxy = document.getElementById("set-proxy").value.trim();
  if (key) payload.gemini_api_key = key;
  if (password) payload.ig_password = password;
  if (proxy) payload.ig_proxy = proxy;
  const result = await post("api/settings", payload);
  show(result.error ? result : { ok: true, detail: "Settings saved on the server." }, true);
  if (result.settings) settings = result.settings;
  await refresh();
}

async function importSession(file) {
  if (!file) return;
  let parsed;
  try {
    parsed = JSON.parse(await file.text());
  } catch (err) {
    show({ ok: false, error: "That file is not JSON." });
    return;
  }
  const result = await post("api/instagram/session", { session: parsed });
  show(result.ok ? { ok: true, detail: "Instagram session imported." } : result, true);
  settings = (await api("api/settings")).settings || settings;
  await refresh();
}

async function enableAlerts() {
  if (!("Notification" in window)) {
    setBanner("This browser cannot show alerts. The status bar on this page still updates.", false);
    return;
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    setBanner("Alerts stay off. The status bar on this page still updates.", false);
    return;
  }
  const session = await api("api/session");
  const key = session.push && session.push.publicKey;
  if (key && "serviceWorker" in navigator && "PushManager" in window) {
    try {
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key),
      });
      await post("api/push/subscribe", { subscription: subscription.toJSON() });
      setBanner("Alerts are on, including when the app is closed.", true);
      return;
    } catch (err) {
      setBanner("On-screen alerts are on. Closed-app push did not subscribe.", false);
      return;
    }
  }
  setBanner("On-screen alerts are on while this app is open. Closed-app push needs VAPID keys on the server.", true);
}

function urlBase64ToUint8Array(value) {
  const padding = "=".repeat((4 - value.length % 4) % 4);
  const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

let refreshing = false;
async function refresh() {
  if (!signedIn || refreshing) return;
  refreshing = true;
  const previous = state;
  try {
    state = await api("api/state");
    const dry = document.getElementById("dry-run");
    if (dry && document.activeElement !== dry) dry.checked = !!state.dry_run;
    paintStatus(previous);
    paintNotice();
    if (view === "today" || view === "clips" || view === "reel" || view === "post") await draw();
  } finally {
    refreshing = false;
  }
}

function route() {
  if (!signedIn) return;
  view = (location.hash || "#today").slice(1);
  if (!titles[view]) view = "today";
  document.getElementById("sheet").hidden = true;
  draw();
}

function showLogin(message) {
  signedIn = false;
  document.getElementById("login").hidden = false;
  document.getElementById("shell").hidden = true;
  paintPasskey();
  const err = document.getElementById("login-error");
  if (message) {
    err.hidden = false;
    err.textContent = message;
  } else {
    err.hidden = true;
    err.textContent = "";
  }
}

function paintPasskey() {
  const supported = typeof PublicKeyCredential !== "undefined";
  const button = document.getElementById("passkey-login");
  const note = document.getElementById("passkey-note");
  const lead = document.getElementById("login-lead");
  const offer = document.getElementById("passkey-offer");
  if (button) button.hidden = !supported || !passkeyReady;
  if (note) note.hidden = !supported || !passkeyReady;
  if (lead) {
    lead.textContent = passkeyReady
      ? "Use the passkey on this iPhone. Face ID or Touch ID confirms it."
      : "Sign in with the password once, then save a passkey for Face ID.";
  }
  if (offer) offer.hidden = !signedIn || !supported || passkeyReady;
}

function b64urlToBuf(value) {
  const pad = "=".repeat((4 - (value.length % 4)) % 4);
  const b64 = (value + pad).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return bytes.buffer;
}

function bufToB64url(buffer) {
  const bytes = new Uint8Array(buffer);
  let raw = "";
  for (const byte of bytes) raw += String.fromCharCode(byte);
  return btoa(raw).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function credentialToJSON(cred) {
  const response = { clientDataJSON: bufToB64url(cred.response.clientDataJSON) };
  if (cred.response.attestationObject) response.attestationObject = bufToB64url(cred.response.attestationObject);
  if (cred.response.authenticatorData) response.authenticatorData = bufToB64url(cred.response.authenticatorData);
  if (cred.response.signature) response.signature = bufToB64url(cred.response.signature);
  if (cred.response.userHandle) response.userHandle = bufToB64url(cred.response.userHandle);
  return { id: cred.id, rawId: bufToB64url(cred.rawId), type: cred.type, response };
}

function creationOptions(publicKey) {
  return Object.assign({}, publicKey, {
    challenge: b64urlToBuf(publicKey.challenge),
    user: Object.assign({}, publicKey.user, { id: b64urlToBuf(publicKey.user.id) }),
    excludeCredentials: (publicKey.excludeCredentials || []).map((cred) => Object.assign({}, cred, { id: b64urlToBuf(cred.id) })),
  });
}

function requestOptions(publicKey) {
  return Object.assign({}, publicKey, {
    challenge: b64urlToBuf(publicKey.challenge),
    allowCredentials: (publicKey.allowCredentials || []).map((cred) => Object.assign({}, cred, { id: b64urlToBuf(cred.id) })),
  });
}

async function createPasskey() {
  if (typeof PublicKeyCredential === "undefined") {
    setBanner("This browser cannot save a passkey. Open the site in Safari.", false);
    return;
  }
  const options = await post("api/passkey/register/options", {});
  if (!options.ok || !options.publicKey) {
    setBanner(options.error || "Could not start the passkey.", false);
    return;
  }
  let cred;
  try {
    cred = await navigator.credentials.create({ publicKey: creationOptions(options.publicKey) });
  } catch (err) {
    setBanner("Passkey was cancelled.", false);
    return;
  }
  const result = await post("api/passkey/register", { credential: credentialToJSON(cred) });
  if (!result.ok) {
    setBanner(result.error || "Could not save the passkey.", false);
    return;
  }
  passkeyReady = true;
  paintPasskey();
  setBanner("Passkey saved. Next time, Face ID or Touch ID signs you in.", true);
  if (view === "settings") route();
}

async function signInWithPasskey() {
  const options = await post("api/passkey/options", {});
  if (!options.ok || !options.publicKey) {
    showLogin(options.error || "Could not start the passkey.");
    return;
  }
  let cred;
  try {
    cred = await navigator.credentials.get({ publicKey: requestOptions(options.publicKey) });
  } catch (err) {
    showLogin("Passkey was cancelled. You can still use the password.");
    return;
  }
  const result = await post("api/passkey/login", { credential: credentialToJSON(cred) });
  if (!result.ok) {
    showLogin(result.error || "Could not sign in with that passkey.");
    return;
  }
  document.getElementById("login-password").value = "";
  await boot();
}

function showShell() {
  signedIn = true;
  document.getElementById("login").hidden = true;
  document.getElementById("shell").hidden = false;
  paintPasskey();
}

document.getElementById("passkey-login").addEventListener("click", () => signInWithPasskey());
document.getElementById("passkey-save").addEventListener("click", () => createPasskey());

document.getElementById("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const result = await post("api/login", { password: document.getElementById("login-password").value });
  if (!result.ok) {
    showLogin(result.error || "Could not sign in.");
    return;
  }
  document.getElementById("login-password").value = "";
  await boot();
});

document.getElementById("dry-run").addEventListener("change", async (event) => {
  const result = await post("api/settings", { dry_run: event.target.checked });
  if (result.settings) settings = result.settings;
  await refresh();
});

document.getElementById("more-btn").addEventListener("click", () => {
  const sheet = document.getElementById("sheet");
  sheet.hidden = !sheet.hidden;
});

document.getElementById("logout").addEventListener("click", async () => {
  await post("api/logout", {});
  showLogin();
});

document.getElementById("sheet").querySelectorAll("a").forEach((link) => {
  link.addEventListener("click", () => {
    document.getElementById("sheet").hidden = true;
  });
});

window.addEventListener("hashchange", route);

async function boot() {
  const session = await api("api/session");
  passkeyReady = !!session.passkey;
  if (session.auth_required && !session.authenticated) {
    showLogin();
    return;
  }
  showShell();
  settings = (await api("api/settings")).settings;
  await refresh();
  route();
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
}

setInterval(refresh, 2000);
boot();
