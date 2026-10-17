const titles = {
  today: "Today",
  prompts: "Prompts",
  clips: "Clips",
  reel: "Reel",
  post: "Post",
  schedule: "Schedule",
  health: "Health",
  settings: "Settings",
  logs: "Logs",
  instagram: "Instagram",
  setup: "Setup",
};

const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
let state = { run: null, busy: false, dry_run: true, scheduler: {}, notice: null, instagram: null };
let settings = null;
let view = "today";
let signedIn = false;
let toastTimer = 0;
let lastPhase = "";
let note = "";

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

function toast(text, ok) {
  const node = document.getElementById("toast");
  if (!node) return;
  node.hidden = false;
  node.className = ok ? "toast" : "toast bad";
  node.textContent = text;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, 4200);
}

async function press(button, pending, doneLabel, work) {
  const original = button ? button.textContent : "";
  if (button) {
    button.disabled = true;
    button.dataset.state = "loading";
    button.textContent = pending;
  }
  let result;
  try {
    result = await work();
  } catch (err) {
    result = { ok: false, error: "That request failed." };
  }
  const waiting = result && (result.state === "needs_code" || result.state === "needs_approval");
  const failed = !waiting && (!result || result.ok === false);
  if (button) {
    button.dataset.state = failed ? "bad" : "ok";
    button.textContent = failed ? "Try again" : (waiting ? "Continue" : (doneLabel || "Done"));
    setTimeout(() => {
      if (!button.isConnected) return;
      button.disabled = false;
      button.dataset.state = "";
      button.textContent = original;
    }, 1400);
  }
  if (waiting) toast(result.message || result.error || "Instagram needs another step.", true);
  else if (failed) toast((result && (result.error || result.detail)) || "Something went wrong.", false);
  else if (result && result.dry_run) toast("Dry run saved. Nothing was sent to Instagram.", true);
  else if (doneLabel) toast(typeof doneLabel === "string" ? doneLabel : "Done.", true);
  else if (result && (result.message || result.detail)) toast(result.message || result.detail, true);
  return result;
}

function statusPill(status, dry) {
  if (status === "posted" && dry) return `<span class="pill dry">dry run</span>`;
  const label = status === "posted" ? "posted" : (status || "draft");
  return `<span class="pill ${esc(status || "")}">${esc(label)}</span>`;
}

function clipCount(run) {
  const prompts = (run && run.prompts) || [];
  const done = prompts.filter((item) => item.status === "ready" || item.status === "failed").length;
  return { done, total: prompts.length };
}

function nextAction(run) {
  if (!run) {
    if (!settings || !settings.gemini_api_key_set) return "Add the Gemini key in Setup, then pull a batch.";
    return "Pull today's trends.";
  }
  const phase = run.phase;
  if (phase === "review") return "Read the prompts, then render clips.";
  if (phase === "rendering") {
    const count = clipCount(run);
    return `Rendering ${count.done} of ${count.total}.`;
  }
  if (phase === "clips_ready") return "Clips are ready. Stitch the reel.";
  if (phase === "branding") return "Stitching the reel.";
  if (phase === "ready" && !run.dry_run && (!state.instagram || state.instagram.state !== "connected")) {
    return "Connect Instagram, then post the reel.";
  }
  if (phase === "ready") return run.dry_run ? "Preview the reel. Dry run is on, so Post now will not upload." : "The reel is ready to post.";
  if (phase === "posting") return "Sending the reel to Instagram.";
  if (phase === "posted" && run.dry_run) return "Dry run saved on the server. Turn off dry run to upload.";
  if (phase === "posted") return "Posted.";
  if (phase === "error") return run.error || "The last job failed.";
  return "Pull today's trends.";
}

function setupGaps() {
  const gaps = [];
  if (!settings || !settings.gemini_api_key_set) gaps.push(["Gemini key", "#setup"]);
  if (!state.instagram || state.instagram.state !== "connected") gaps.push(["Instagram", "#instagram"]);
  const sched = settings && settings.schedule;
  if (!sched || (!sched.batch_enabled && !sched.post_enabled)) gaps.push(["Schedule", "#schedule"]);
  return gaps;
}

function renderToday() {
  const run = state.run;
  const gaps = setupGaps();
  const setup = gaps.length ? `<a class="card next-card" href="${gaps[0][1]}"><strong>Finish setup</strong><p class="muted">${esc(gaps.map((item) => item[0]).join(" · "))}</p></a>` : "";
  const count = clipCount(run);
  const steps = [
    ["Trends", run ? "Done" : "Wait"],
    ["Prompts", run ? "Done" : "Wait"],
    ["Veo", run && ["rendering", "clips_ready", "branding", "ready", "posting", "posted"].includes(run.phase) ? (run.phase === "rendering" ? `${count.done}/${count.total}` : "Done") : "Wait"],
    ["Brand", run && ["branding", "ready", "posting", "posted"].includes(run.phase) ? (run.phase === "branding" ? "Now" : "Done") : "Wait"],
    ["Post", run && ["ready", "posting", "posted"].includes(run.phase) ? (run.phase === "posted" ? (run.dry_run ? "Dry" : "Done") : "Now") : "Wait"],
  ];
  const trends = ((run && run.trends) || []).slice(0, 8).map((topic) => `<span class="chip">${esc(topic)}</span>`).join("");
  return `
    ${setup}
    <article class="card next-card"><strong>What's next</strong><p>${esc(nextAction(run))}</p></article>
    <div class="steps">${steps.map(([name, label]) => `<div class="step"><strong>${name}</strong><em>${esc(label)}</em></div>`).join("")}</div>
    <label class="field switch"><span>Dry run</span><input type="checkbox" id="dry-run" ${state.dry_run ? "checked" : ""}></label>
    <div class="row">
      <button class="btn primary" id="act-batch" type="button" ${state.busy ? "disabled" : ""}>New batch</button>
      <button class="btn" id="act-render" type="button" ${state.busy || !run ? "disabled" : ""}>Render clips</button>
      <button class="btn" id="act-brand" type="button" ${state.busy || !run ? "disabled" : ""}>Stitch and brand</button>
      <a class="btn" href="#post">Open post</a>
    </div>
    <div class="card"><strong>Trends</strong><div class="chips">${trends || '<span class="chip">None yet</span>'}</div></div>`;
}

function preview(text) {
  const body = esc(text || "");
  return `<p class="clamp">${body}</p><button class="btn linkish expand" type="button">Show all</button>`;
}

function renderPrompts() {
  const prompts = (state.run && state.run.prompts) || [];
  if (!prompts.length) return `<p class="muted">Generate a batch on Today first.</p>`;
  return prompts.map((prompt) => `
    <article class="prompt" data-id="${esc(prompt.id)}">
      <p class="name">${esc(prompt.channel)}</p> ${statusPill(prompt.status, state.run && state.run.dry_run)}
      <label class="field"><span>Veo prompt</span><textarea class="prompt-text">${esc(prompt.prompt)}</textarea></label>
      <label class="field"><span>Caption</span><textarea class="caption-text">${esc(prompt.caption)}</textarea></label>
      ${prompt.error ? `<p class="warn">${esc(prompt.error)}</p>` : ""}
      <button class="btn regen" type="button">Regenerate this one</button>
    </article>`).join("") + `<div class="row"><button class="btn primary" id="save-prompts" type="button">Save edits</button></div>`;
}

function player(src, poster) {
  if (!src) return `<p class="muted">No file yet.</p>`;
  const posterAttr = poster ? ` data-poster="${esc(poster)}"` : "";
  const still = poster ? `<img src="${esc(poster)}" alt="">` : "";
  return `<button class="player" type="button" data-src="${esc(src)}"${posterAttr} aria-label="Play">${still}<span class="play">Play</span></button>`;
}

function renderClips() {
  const prompts = (state.run && state.run.prompts) || [];
  if (!prompts.length) return `<p class="muted">No clips yet. Render them from Today.</p>`;
  return prompts.map((prompt) => {
    const poster = prompt.clip ? `media/posters/${prompt.clip.replace(/\.mp4$/, ".png")}` : "";
    const src = prompt.clip ? `media/clips/${prompt.clip}` : "";
    return `<article class="clip"><h3>${esc(prompt.channel)}</h3> ${statusPill(prompt.status, state.run && state.run.dry_run)}${player(src, poster)}${preview(prompt.prompt)}${prompt.error ? `<p class="warn">${esc(prompt.error)}</p>` : ""}</article>`;
  }).join("");
}

function renderReel() {
  const run = state.run;
  if (!run || !run.reel) return `<p class="muted">Stitch a reel from Today after at least one clip is ready.</p>`;
  const poster = run.poster ? `media/posters/${run.poster}` : "";
  return `
    <article class="card reel">
      <h2>Today's reel</h2>
      ${player(`media/reels/${run.reel}`, poster)}
      <div class="row"><a class="btn primary" href="#post">Open post</a></div>
    </article>`;
}

function renderPost(history) {
  const run = state.run;
  const caption = (run && run.prompts && run.prompts[0] && run.prompts[0].caption) || "";
  const rows = (history || []).slice().reverse().map((item) => {
    let result = item.url || item.error || "";
    if (item.dry_run) result = "Saved on the server. Nothing was sent to Instagram.";
    else if (item.ok && !item.url) result = "Posted.";
    return `<div class="history-row"><strong>${esc((item.at || "").replace("T", " ").slice(0, 16))}</strong><p class="muted">${esc(result)}</p></div>`;
  }).join("");
  const ig = state.instagram;
  const connect = ig && ig.state === "connected" ? "" : `<a class="card next-card" href="#instagram"><strong>Connect Instagram</strong><p class="muted">Post now cannot upload until the account is connected.</p></a>`;
  const saved = note ? `<article class="card"><strong>Last result</strong><p>${esc(note)}</p></article>` : "";
  return `
    ${saved}
    ${connect}
    <label class="field"><span>Caption</span><textarea id="post-caption">${esc(caption)}</textarea></label>
    <div class="row">
      <button class="btn primary" id="do-post" type="button" ${run && run.reel && !state.busy ? "" : "disabled"}>Post now</button>
    </div>
    <p class="muted">${state.dry_run ? "Dry run is on. Post now saves a history row and does not upload." : "Dry run is off. Post now uploads to the connected account."}</p>
    <h2>History</h2>
    ${rows || `<p class="muted">Nothing saved yet.</p>`}`;
}

function renderSchedule() {
  const sched = (settings && settings.schedule) || { weekdays: [], batch_time: "09:00", post_time: "12:00" };
  const zone = (settings && settings.timezone) || "America/New_York";
  const next = state.scheduler || {};
  const days = dayNames.map((name, index) => `
    <label><input type="checkbox" class="day" value="${index}" ${(sched.weekdays || []).includes(index) ? "checked" : ""}> ${name}</label>`).join("");
  const batchLine = sched.batch_enabled
    ? `Next run ${esc(next.next_batch || "soon")}. ${next.last_batch_date ? "Last ran " + esc(next.last_batch_date) + "." : "Has not run yet."}`
    : "Off. Turn it on, pick a time, and save.";
  const postLine = sched.post_enabled
    ? `Next run ${esc(next.next_post || "soon")}. ${next.last_post_date ? "Last ran " + esc(next.last_post_date) + "." : "Has not run yet."}`
    : "Off. Turn it on, pick a time, and save.";
  return `
    <p class="muted">Times are ${esc(zone)}.</p>
    <label class="field"><span><input type="checkbox" id="batch-on" ${sched.batch_enabled ? "checked" : ""}> Morning batch</span>
      <input type="time" id="batch-time" value="${esc(sched.batch_time)}"></label>
    <p class="muted">${batchLine}</p>
    <label class="field"><span><input type="checkbox" id="post-on" ${sched.post_enabled ? "checked" : ""}> Midday post</span>
      <input type="time" id="post-time" value="${esc(sched.post_time)}"></label>
    <p class="muted">${postLine}</p>
    <div class="days">${days}</div>
    <div class="row"><button class="btn primary" id="save-schedule" type="button">Save schedule</button></div>`;
}

function renderHealth(health) {
  if (!health) return `<p class="muted">Loading…</p>`;
  const cards = [["Veo", health.veo], ["Instagram", health.instagram], ["OpenClaw", health.openclaw], ["ffmpeg", health.ffmpeg], ["Disk", health.disk], ["Output", health.output]];
  return `<div class="health">${cards.map(([name, card]) => `
    <article class="health-card"><h3>${esc(name)} ${card.ok ? '<span class="pill ok">ok</span>' : '<span class="pill bad">check</span>'}</h3><p>${esc(card.detail || "")}</p></article>`).join("")}</div>
    <div class="row">
      <button class="btn" id="test-veo" type="button">Test Veo key</button>
      <button class="btn" id="enable-alerts" type="button">Allow alerts</button>
      <a class="btn" href="#instagram">Connect Instagram</a>
    </div>`;
}

function renderSettings() {
  if (!settings) return `<p class="muted">Loading…</p>`;
  return `
    <article class="card">
      <h2>Veo</h2>
      <label class="field"><span>Gemini API key ${settings.gemini_api_key_set ? "(" + esc(settings.gemini_api_key_mask) + ")" : ""}</span>
        <input id="set-key" type="password" autocomplete="off" placeholder="${settings.gemini_api_key_set ? "Leave blank to keep it" : "From aistudio.google.com"}"></label>
      <label class="field"><span>Model</span><input id="set-model" type="text" value="${esc(settings.veo_model)}"></label>
      <label class="field"><span>Clip length</span>
        <select id="set-duration">${[4, 6, 8].map((n) => `<option ${Number(settings.veo_duration_seconds) === n ? "selected" : ""}>${n}</option>`).join("")}</select></label>
      <div class="row"><button class="btn primary" id="save-veo" type="button">Save Veo</button></div>
    </article>
    <article class="card">
      <h2>Instagram</h2>
      <p class="muted">${state.instagram && state.instagram.state === "connected" ? "Connected as " + esc(state.instagram.username) + "." : "Not connected."}</p>
      <a class="btn" href="#instagram">Open Connect Instagram</a>
    </article>
    <article class="card">
      <h2>Server</h2>
      <label class="field"><span>Timezone</span><input id="set-tz" type="text" value="${esc(settings.timezone)}"></label>
      <label class="field"><span>Trends country</span><input id="set-geo" type="text" value="${esc(settings.trends_geo)}"></label>
      <label class="field"><span>Batch size</span><input id="set-count" type="number" min="1" max="8" value="${esc(settings.batch_size)}"></label>
      <label class="field"><span>ffmpeg, if it is not on PATH</span><input id="set-ff" type="text" value="${esc(settings.ffmpeg_path)}" placeholder="Leave blank on the server"></label>
      <label class="field"><span><input type="checkbox" id="set-claw-on" ${settings.openclaw_enabled ? "checked" : ""}> Check an OpenClaw gateway</span>
        <input id="set-claw" type="text" value="${esc(settings.openclaw_url)}" placeholder="Off unless a PC is on"></label>
      <div class="row"><button class="btn primary" id="save-server" type="button">Save server settings</button></div>
    </article>`;
}

function renderInstagram() {
  const ig = state.instagram || { state: "disconnected", username: (settings && settings.ig_username) || "" };
  if (ig.state === "connected") {
    return `
      <article class="card">
        <h2>Connected</h2>
        <p>Signed in as <strong>${esc(ig.username || (settings && settings.ig_username) || "your account")}</strong>. The session is encrypted on the server.</p>
        <div class="row">
          <button class="btn" id="ig-check" type="button">Check session</button>
          <button class="btn" id="ig-disconnect" type="button">Disconnect</button>
        </div>
      </article>
      ${proxyCard()}
      ${importCard()}`;
  }
  if (ig.state === "needs_code") {
    return `
      <article class="card">
        <h2>Enter the code</h2>
        <p>${esc(ig.message || "Instagram sent a 6-digit code. Type it here. This is not the vidrot password.")}</p>
        <label class="field"><span>6-digit code</span><input id="ig-code" type="text" inputmode="numeric" autocomplete="one-time-code"></label>
        <div class="row"><button class="btn primary" id="ig-submit-code" type="button">Submit code</button></div>
      </article>`;
  }
  if (ig.state === "needs_approval") {
    return `
      <article class="card">
        <h2>Approve on your phone</h2>
        <p>${esc(ig.message || "Open the Instagram app and approve the login prompt. Then come back here.")}</p>
        <div class="row"><button class="btn primary" id="ig-approve" type="button">I approved it</button></div>
        <label class="field"><span>Or the code Instagram texted or emailed</span><input id="ig-code" type="text" inputmode="numeric" autocomplete="one-time-code"></label>
        <div class="row"><button class="btn" id="ig-submit-code" type="button">Submit code</button></div>
      </article>
      ${proxyCard()}`;
  }
  return `
    <article class="card">
      <h2>Connect Instagram</h2>
      <p>Sign in with the account that should post the reels. The password is sent to this server, used once for instagrapi, and the session is stored encrypted.</p>
      <label class="field"><span>Username</span><input id="ig-user" type="text" autocomplete="username" value="${esc(ig.username || (settings && settings.ig_username) || "")}"></label>
      <label class="field"><span>Password ${settings && settings.ig_password_set ? "(saved — leave blank to use it)" : ""}</span>
        <input id="ig-pass" type="password" autocomplete="current-password"></label>
      <div class="row"><button class="btn primary" id="ig-connect" type="button">Connect</button></div>
      ${ig.message ? `<p class="warn">${esc(ig.message)}</p>` : ""}
    </article>
    ${proxyCard()}
    ${importCard()}`;
}

function proxyCard() {
  const set = settings && settings.ig_proxy_set;
  return `
    <article class="card">
      <h2>If Instagram blocks this server</h2>
      <p class="muted">A datacenter IP often gets a checkpoint or a locked login. Point this at a proxy you control, such as a machine at home, and connect again. Leave it blank to try directly.</p>
      <label class="field"><span>Proxy ${set ? "(" + esc(settings.ig_proxy_mask) + " saved)" : ""}</span>
        <input id="ig-proxy" type="text" placeholder="http://user:pass@home-proxy:8080" autocomplete="off"></label>
      <div class="row"><button class="btn" id="ig-save-proxy" type="button">Save proxy</button></div>
    </article>`;
}

function importCard() {
  return `
    <article class="card">
      <h2>Advanced: import session.json</h2>
      <p class="muted">On the old PC the file is C:\\Users\\dejes\\.openclaw\\instagram_sessions\\session.json. AirDrop or copy it to this phone, then choose it here. The server encrypts it and deletes the plaintext copy.</p>
      <label class="field"><span>session.json</span><input id="set-session" type="file" accept="application/json,.json"></label>
    </article>`;
}

function renderSetup() {
  const key = settings && settings.gemini_api_key_set;
  const ig = state.instagram && state.instagram.state === "connected";
  const sched = settings && settings.schedule && (settings.schedule.batch_enabled || settings.schedule.post_enabled);
  return `
    <article class="card"><h2>1. This phone</h2><p class="muted">${signedIn ? "You're signed in." : "Sign in with the owner password."}</p></article>
    <article class="card">
      <h2>2. Gemini key ${key ? "· saved" : ""}</h2>
      <label class="field"><span>Key ${key ? "(" + esc(settings.gemini_api_key_mask) + ")" : ""}</span>
        <input id="setup-key" type="password" autocomplete="off" placeholder="${key ? "Leave blank to test the saved key" : "From aistudio.google.com"}"></label>
      <div class="row">
        <button class="btn primary" id="setup-save-key" type="button">Save and test</button>
      </div>
    </article>
    <article class="card"><h2>3. Instagram ${ig ? "· connected" : ""}</h2><a class="btn" href="#instagram">${ig ? "Review connection" : "Connect Instagram"}</a></article>
    <article class="card"><h2>4. Schedule ${sched ? "· on" : ""}</h2><a class="btn" href="#schedule">Set the morning and midday times</a></article>`;
}

function renderLogs(lines) {
  const ordered = (lines || []).slice().reverse();
  return `<div class="card"><div class="log">${esc(ordered.join("\n")) || "Log is empty."}</div></div>`;
}

function renderMissing() {
  return `<article class="card"><h2>That page is not in the app</h2><p class="muted">The link does not match a screen.</p><a class="btn" href="#today">Back to Today</a></article>`;
}

function paintProgress(previous) {
  const node = document.getElementById("progress");
  const run = state.run;
  const phase = run ? run.phase : "";
  const busy = !!state.busy;
  const show = busy || phase === "error";
  node.hidden = !show;
  if (!show) {
    if (previous && previous.run && phase && previous.run.phase !== phase) announce(previous.run.phase, phase);
    lastPhase = phase;
    return;
  }
  const count = clipCount(run);
  let text = "Working";
  let pct = 0;
  if (phase === "rendering") {
    text = `Rendering ${count.done} of ${count.total}`;
    pct = count.total ? Math.round((count.done / count.total) * 100) : 8;
  } else if (phase === "branding") {
    text = "Stitching the reel";
    pct = 70;
  } else if (phase === "posting") {
    text = "Posting to Instagram";
    pct = 85;
  } else if (phase === "error") {
    text = (run && run.error) || "The job failed";
    pct = 0;
  }
  document.getElementById("progress-text").textContent = text;
  const bar = document.getElementById("progress-bar");
  bar.hidden = phase === "error";
  document.getElementById("progress-fill").style.width = pct + "%";
  if (previous && previous.run && phase && previous.run.phase !== phase) announce(previous.run.phase, phase);
  lastPhase = phase;
}

function announce(prev, next) {
  if (!prev || prev === next) return;
  if (next === "clips_ready") toast("Clips are ready.", true);
  if (next === "ready") toast("Reel is ready.", true);
  if (next === "posted" && state.run && state.run.dry_run) toast("Dry run saved. Nothing was sent to Instagram.", true);
  if (next === "posted" && state.run && !state.run.dry_run) toast("Posted to Instagram.", true);
  if (next === "error") toast((state.run && state.run.error) || "The job failed.", false);
}

function closeSheet() {
  document.getElementById("sheet").hidden = true;
  document.getElementById("backdrop").hidden = true;
  document.getElementById("more-btn").setAttribute("aria-expanded", "false");
}

function openSheet() {
  document.getElementById("sheet").hidden = false;
  document.getElementById("backdrop").hidden = false;
  document.getElementById("more-btn").setAttribute("aria-expanded", "true");
}

async function draw() {
  const root = document.getElementById("view");
  document.getElementById("title").textContent = titles[view] || "vidrot";
  document.querySelectorAll("#nav a").forEach((link) => {
    link.classList.toggle("on", link.dataset.view === view);
  });
  if (view === "today") root.innerHTML = renderToday();
  else if (view === "prompts") root.innerHTML = renderPrompts();
  else if (view === "clips") root.innerHTML = renderClips();
  else if (view === "reel") root.innerHTML = renderReel();
  else if (view === "post") root.innerHTML = renderPost((await api("api/history")).posts);
  else if (view === "schedule") root.innerHTML = renderSchedule();
  else if (view === "health") root.innerHTML = renderHealth((await api("api/health")).health);
  else if (view === "settings") root.innerHTML = renderSettings();
  else if (view === "logs") root.innerHTML = renderLogs((await api("api/logs")).lines);
  else if (view === "instagram") root.innerHTML = renderInstagram();
  else if (view === "setup") root.innerHTML = renderSetup();
  else root.innerHTML = renderMissing();
  wire();
}

function wire() {
  document.querySelectorAll(".player img").forEach((img) => {
    img.addEventListener("error", () => img.remove());
  });
  document.querySelectorAll(".player").forEach((button) => {
    button.onclick = () => {
      const video = document.createElement("video");
      video.src = button.dataset.src;
      video.controls = true;
      video.playsInline = true;
      video.autoplay = true;
      if (button.dataset.poster) video.poster = button.dataset.poster;
      video.className = "clip-video";
      button.replaceWith(video);
    };
  });
  document.querySelectorAll(".expand").forEach((button) => {
    button.onclick = () => {
      const clamp = button.previousElementSibling;
      const open = clamp.classList.toggle("open");
      button.textContent = open ? "Show less" : "Show all";
    };
  });
  const batch = document.getElementById("act-batch");
  if (batch) batch.onclick = () => press(batch, "Pulling trends…", "Batch ready", async () => {
    const result = await post("api/batch", {});
    await refresh();
    return result;
  });
  const render = document.getElementById("act-render");
  if (render) render.onclick = () => press(render, "Starting…", "Render started", async () => {
    const result = await post("api/render", {});
    await refresh();
    return result;
  });
  const brand = document.getElementById("act-brand");
  if (brand) brand.onclick = () => press(brand, "Starting…", "Stitch started", async () => {
    const result = await post("api/brand", {});
    await refresh();
    return result;
  });
  const dry = document.getElementById("dry-run");
  if (dry) dry.onchange = async () => {
    const result = await post("api/settings", { dry_run: dry.checked });
    if (result.settings) settings = result.settings;
    toast(dry.checked ? "Dry run is on." : "Dry run is off. Posts will upload.", result.ok !== false);
    await refresh();
  };
  document.querySelectorAll(".regen").forEach((button) => {
    button.onclick = () => press(button, "Rewriting…", "Prompt updated", async () => {
      const article = button.closest(".prompt");
      const result = await post("api/prompts/regenerate", { id: article.dataset.id });
      const fresh = ((result.run && result.run.prompts) || []).find((item) => item.id === article.dataset.id);
      if (fresh) {
        article.querySelector(".prompt-text").value = fresh.prompt;
        article.querySelector(".caption-text").value = fresh.caption;
        if (state.run) state.run = result.run;
      }
      return result;
    });
  });
  const savePromptsBtn = document.getElementById("save-prompts");
  if (savePromptsBtn) savePromptsBtn.onclick = () => press(savePromptsBtn, "Saving…", "Edits saved", async () => {
    const prompts = [...document.querySelectorAll(".prompt")].map((node) => ({
      id: node.dataset.id,
      prompt: node.querySelector(".prompt-text").value,
      caption: node.querySelector(".caption-text").value,
    }));
    const result = await post("api/prompts", { prompts });
    if (result.run) state.run = result.run;
    return result;
  });
  const doPost = document.getElementById("do-post");
  if (doPost) doPost.onclick = () => press(doPost, "Posting…", "Saved", async () => {
    const result = await post("api/post", { caption: document.getElementById("post-caption").value });
    if (result && result.dry_run) note = "Dry run saved. Nothing was sent to Instagram.";
    else if (result && result.ok) note = result.url || "Posted to Instagram.";
    else if (result && result.error) note = result.error;
    await refresh();
    if (view === "post") await draw();
    return result;
  });
  const saveSched = document.getElementById("save-schedule");
  if (saveSched) saveSched.onclick = () => press(saveSched, "Saving…", "Schedule saved", saveSchedule);
  const testVeo = document.getElementById("test-veo");
  if (testVeo) testVeo.onclick = () => press(testVeo, "Checking…", "Veo key works", () => post("api/veo/test", {}));
  const alerts = document.getElementById("enable-alerts");
  if (alerts) alerts.onclick = () => press(alerts, "Asking…", "Alerts on", enableAlerts);
  const saveVeo = document.getElementById("save-veo");
  if (saveVeo) saveVeo.onclick = () => press(saveVeo, "Saving…", "Veo saved", () => savePart({
    gemini_api_key: document.getElementById("set-key").value,
    veo_model: document.getElementById("set-model").value,
    veo_duration_seconds: Number(document.getElementById("set-duration").value),
  }));
  const saveServer = document.getElementById("save-server");
  if (saveServer) saveServer.onclick = () => press(saveServer, "Saving…", "Settings saved", () => savePart({
    timezone: document.getElementById("set-tz").value,
    trends_geo: document.getElementById("set-geo").value,
    batch_size: Number(document.getElementById("set-count").value),
    ffmpeg_path: document.getElementById("set-ff").value,
    openclaw_enabled: document.getElementById("set-claw-on").checked,
    openclaw_url: document.getElementById("set-claw").value,
  }));
  const sessionFile = document.getElementById("set-session");
  if (sessionFile) sessionFile.onchange = () => importSession(sessionFile.files && sessionFile.files[0], sessionFile);
  const connect = document.getElementById("ig-connect");
  if (connect) connect.onclick = () => press(connect, "Connecting…", "Connected", connectInstagram);
  const submitCode = document.getElementById("ig-submit-code");
  if (submitCode) submitCode.onclick = () => press(submitCode, "Sending…", "Connected", async () => {
    const result = await post("api/instagram/connect/code", { code: document.getElementById("ig-code").value });
    applyIg(result);
    return result;
  });
  const approve = document.getElementById("ig-approve");
  if (approve) approve.onclick = () => press(approve, "Checking…", "Connected", async () => {
    const result = await post("api/instagram/connect/approve", {});
    applyIg(result);
    return result;
  });
  const disconnect = document.getElementById("ig-disconnect");
  if (disconnect) disconnect.onclick = () => press(disconnect, "Removing…", "Disconnected", async () => {
    const result = await post("api/instagram/disconnect", {});
    applyIg(result);
    return result;
  });
  const check = document.getElementById("ig-check");
  if (check) check.onclick = () => press(check, "Checking…", "Session works", () => post("api/instagram/test", {}));
  const saveProxy = document.getElementById("ig-save-proxy");
  if (saveProxy) saveProxy.onclick = () => press(saveProxy, "Saving…", "Proxy saved", () => savePart({ ig_proxy: document.getElementById("ig-proxy").value }));
  const setupKey = document.getElementById("setup-save-key");
  if (setupKey) setupKey.onclick = () => press(setupKey, "Testing…", "Key works", async () => {
    const key = document.getElementById("setup-key").value;
    if (key) {
      const saved = await savePart({ gemini_api_key: key });
      if (saved.ok === false) return saved;
    }
    const result = await post("api/veo/test", {});
    return result.ok === false ? result : { ok: true, detail: result.detail || "Veo key works." };
  });
}

async function savePart(payload) {
  Object.keys(payload).forEach((key) => {
    if (payload[key] === "" && (key === "gemini_api_key" || key === "ig_password")) delete payload[key];
  });
  const result = await post("api/settings", payload);
  if (result.settings) settings = result.settings;
  return result;
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
  if (result.settings) settings = result.settings;
  if (result.scheduler) state.scheduler = result.scheduler;
  return result;
}

function applyIg(result) {
  if (!result) return;
  if (result.settings) settings = result.settings;
  if (result.state) {
    state.instagram = {
      state: result.state,
      username: result.username || (state.instagram && state.instagram.username) || "",
      message: result.message || result.error || "",
      session_saved: result.state === "connected",
    };
  }
  if (view === "instagram" || view === "setup" || view === "today") draw();
}

async function connectInstagram() {
  const payload = {
    username: document.getElementById("ig-user").value,
    password: document.getElementById("ig-pass").value,
  };
  const proxy = document.getElementById("ig-proxy");
  if (proxy && proxy.value.trim()) payload.proxy = proxy.value.trim();
  const result = await post("api/instagram/connect", payload);
  applyIg(result);
  return result;
}

async function importSession(file, input) {
  if (!file) return;
  let parsed;
  try {
    parsed = JSON.parse(await file.text());
  } catch (err) {
    toast("That file is not JSON.", false);
    return;
  }
  const result = await post("api/instagram/session", { session: parsed });
  if (result.ok) {
    state.instagram = { state: "connected", username: (settings && settings.ig_username) || "", message: "", session_saved: true };
    settings = (await api("api/settings")).settings || settings;
    toast("Instagram session imported.", true);
    if (view === "instagram") await draw();
  } else toast(result.error || "Could not import that file.", false);
  if (input) input.value = "";
}

async function enableAlerts() {
  if (!("Notification" in window)) return { ok: false, error: "This browser has no alerts." };
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return { ok: false, error: "Alerts stay off until you allow them." };
  const session = await api("api/session");
  const key = session.push && session.push.publicKey;
  if (key && "serviceWorker" in navigator && "PushManager" in window) {
    const ready = await navigator.serviceWorker.ready;
    const subscription = await ready.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(key),
    });
    await post("api/push/subscribe", { subscription: subscription.toJSON() });
    return { ok: true, detail: "Alerts are on, including when the app is closed." };
  }
  return { ok: true, detail: "On-screen alerts are on while the app is open." };
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
    const next = await api("api/state");
    if (!next || next.ok === false) return;
    state = next;
    paintProgress(previous);
    const focused = document.activeElement && document.getElementById("view").contains(document.activeElement);
    const live = view === "today" || view === "clips" || view === "reel";
    if (live && !focused) await draw();
  } finally {
    refreshing = false;
  }
}

function route() {
  if (!signedIn) return;
  const asked = (location.hash || "#today").slice(1);
  view = titles[asked] ? asked : "missing";
  closeSheet();
  document.getElementById("main").scrollTop = 0;
  draw();
}

function showLogin(message) {
  signedIn = false;
  const login = document.getElementById("login");
  login.hidden = false;
  login.removeAttribute("aria-hidden");
  document.getElementById("shell").hidden = true;
  const err = document.getElementById("login-error");
  if (message) {
    err.hidden = false;
    err.textContent = message;
  } else {
    err.hidden = true;
  }
}

function showShell() {
  signedIn = true;
  const login = document.getElementById("login");
  login.hidden = true;
  login.setAttribute("aria-hidden", "true");
  document.getElementById("shell").hidden = false;
}

document.getElementById("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.target.querySelector("button[type=submit]");
  await press(button, "Signing in…", "", async () => {
    const result = await post("api/login", { password: document.getElementById("login-password").value });
    if (!result.ok) return result;
    document.getElementById("login-password").value = "";
    await boot();
    return { ok: true };
  });
});

document.getElementById("more-btn").addEventListener("click", () => {
  if (document.getElementById("sheet").hidden) openSheet();
  else closeSheet();
});
document.getElementById("tab-more").addEventListener("click", openSheet);
document.getElementById("sheet-close").addEventListener("click", closeSheet);
document.getElementById("backdrop").addEventListener("click", closeSheet);
document.getElementById("sheet").querySelectorAll("a").forEach((link) => {
  link.addEventListener("click", closeSheet);
});
document.getElementById("logout").addEventListener("click", async () => {
  closeSheet();
  await post("api/logout", {});
  showLogin();
});
window.addEventListener("hashchange", route);

async function boot() {
  const session = await api("api/session");
  if (session.auth_required && !session.authenticated) {
    showLogin();
    return;
  }
  showShell();
  settings = (await api("api/settings")).settings;
  await refresh();
  route();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
}

setInterval(refresh, 2000);
boot();
