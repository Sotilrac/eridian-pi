/* ROCKY // VOX control panel. No dependencies: the figurine may live on a
   LAN with no route to the internet. */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const field = (name) => document.querySelectorAll(`[data-field="${name}"]`);
  const setField = (name, text) => field(name).forEach((el) => { el.textContent = text; });

  /* ---------------- starfield ---------------- */
  const canvas = $("#starfield");
  const ctx = canvas.getContext("2d");
  let stars = [];

  function seedStars() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.floor(window.innerWidth * dpr);
    canvas.height = Math.floor(window.innerHeight * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const area = window.innerWidth * window.innerHeight;
    const count = Math.min(520, Math.round(area / 2600));
    stars = Array.from({ length: count }, () => ({
      x: Math.random() * window.innerWidth,
      y: Math.random() * window.innerHeight,
      r: Math.random() < 0.9 ? Math.random() * 0.8 + 0.2 : Math.random() * 1.3 + 0.9,
      a: Math.random() * 0.55 + 0.12,
      // Slow, independent twinkle so nothing pulses in lockstep.
      speed: Math.random() * 0.0009 + 0.0002,
      phase: Math.random() * Math.PI * 2,
    }));
  }

  function paint(t) {
    ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    ctx.fillStyle = "#cfe3f0";
    for (const s of stars) {
      const twinkle = t === null ? 1 : 0.72 + 0.28 * Math.sin(t * s.speed + s.phase);
      ctx.globalAlpha = s.a * twinkle;
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  function animate(t) {
    paint(t);
    requestAnimationFrame(animate);
  }

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  seedStars();
  if (reduceMotion) paint(null); else requestAnimationFrame(animate);

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { seedStars(); if (reduceMotion) paint(null); }, 180);
  });

  /* ---------------- api ---------------- */
  async function api(path, options = {}) {
    const response = await fetch(path, options);
    let body = {};
    try { body = await response.json(); } catch { /* empty body is fine */ }
    if (!response.ok) throw new Error(body.error || `request failed (${response.status})`);
    return body;
  }

  const notice = $("#notice");
  let noticeTimer;
  function say(message, ok = false) {
    clearTimeout(noticeTimer);
    if (!message) { notice.hidden = true; return; }
    notice.textContent = message;
    notice.classList.toggle("is-ok", ok);
    notice.hidden = false;
    noticeTimer = setTimeout(() => { notice.hidden = true; }, 6000);
  }

  /* ---------------- volume ---------------- */
  const volbar = $("#volbar");
  const segments = [];
  for (let i = 0; i < 64; i += 1) {
    const seg = document.createElement("span");
    seg.className = "vol__seg";
    volbar.appendChild(seg);
    segments.push(seg);
  }

  let volume = 0;
  let volumeMax = 63;
  let volumeDirty = false; // suppress polled values while the user is dragging

  function paintVolume() {
    setField("volume", String(volume).padStart(2, "0"));
    setField("volume-max", String(volumeMax));
    setField("volume-ceiling-label", volumeMax < 63 ? `capped ${volumeMax}` : "max 63");
    volbar.setAttribute("aria-valuenow", String(volume));
    volbar.setAttribute("aria-valuemax", String(volumeMax));
    segments.forEach((seg, i) => {
      seg.classList.toggle("is-on", i < volume);
      seg.classList.toggle("is-over", i >= volumeMax);
    });
  }

  let sendTimer;
  function requestVolume(value) {
    volume = Math.max(0, Math.min(volumeMax, Math.round(value)));
    volumeDirty = true;
    paintVolume();
    clearTimeout(sendTimer);
    sendTimer = setTimeout(async () => {
      try {
        const result = await api("/api/volume", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ value: volume }),
        });
        volume = result.volume;
        paintVolume();
      } catch (err) {
        say(err.message);
      } finally {
        volumeDirty = false;
      }
    }, 120);
  }

  function volumeFromEvent(event) {
    const rect = volbar.getBoundingClientRect();
    const ratio = (event.clientX - rect.left) / rect.width;
    return Math.round(Math.max(0, Math.min(1, ratio)) * 63);
  }

  volbar.addEventListener("pointerdown", (event) => {
    volbar.setPointerCapture(event.pointerId);
    requestVolume(volumeFromEvent(event));
  });
  volbar.addEventListener("pointermove", (event) => {
    if (event.buttons) requestVolume(volumeFromEvent(event));
  });
  volbar.addEventListener("keydown", (event) => {
    const step = event.shiftKey ? 5 : 1;
    if (event.key === "ArrowRight" || event.key === "ArrowUp") requestVolume(volume + step);
    else if (event.key === "ArrowLeft" || event.key === "ArrowDown") requestVolume(volume - step);
    else if (event.key === "Home") requestVolume(0);
    else if (event.key === "End") requestVolume(volumeMax);
    else return;
    event.preventDefault();
  });

  /* ---------------- clip list ---------------- */
  const clipList = $("#clips");
  const clipEmpty = $("#clips-empty");

  function formatDuration(seconds) {
    if (!seconds) return "--:--";
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function clipRow(index, { name, meta, cls, actions }) {
    const li = document.createElement("li");
    li.className = `clip ${cls}`.trim();

    const idx = document.createElement("span");
    idx.className = "clip__idx";
    idx.textContent = String(index).padStart(2, "0");

    const body = document.createElement("span");
    body.className = "clip__name";
    body.textContent = name;
    const sub = document.createElement("span");
    sub.className = "clip__meta";
    sub.textContent = meta;
    body.appendChild(sub);

    const acts = document.createElement("span");
    acts.className = "clip__acts";
    for (const action of actions) acts.appendChild(action);

    li.append(idx, body, acts);
    return li;
  }

  function actionButton(label, onClick, alert = false) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `btn btn--tight${alert ? " btn--alert" : ""}`;
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
  }

  function renderClips(state) {
    clipList.replaceChildren();
    let index = 0;

    for (const clip of state.clips) {
      index += 1;
      const isPlaying = state.playing && state.current_id === clip.id;
      const meta = [
        formatDuration(clip.duration),
        clip.locked ? "built-in · locked" : `${Math.round(clip.size / 1024)}KB`,
      ].join(" · ");

      const actions = [actionButton("Play", () => preview(clip.id))];
      if (!clip.locked) {
        actions.push(actionButton("Del", () => remove(clip.id, clip.title), true));
      }

      clipList.appendChild(clipRow(index, {
        name: clip.title,
        meta,
        cls: `${clip.locked ? "is-locked" : ""} ${isPlaying ? "is-playing" : ""}`.trim(),
        actions,
      }));
    }

    for (const job of state.jobs) {
      index += 1;
      const failed = job.status === "failed";
      const actions = failed ? [actionButton("Dismiss", () => { dismissed.add(job.id); refresh(); })] : [];
      clipList.appendChild(clipRow(index, {
        name: job.title,
        meta: failed
          ? `rejected · ${job.error}`
          : `processing · ${job.kind === "speech" ? "synthesising" : "transcoding"}`,
        cls: failed ? "is-failed" : "is-pending",
        actions,
      }));
    }

    const total = state.clips.length;
    clipEmpty.hidden = index > 0;
    setField("clipcount", `${total} clip${total === 1 ? "" : "s"} in rotation`);
  }

  const dismissed = new Set();

  async function preview(id) {
    try { await api(`/api/clips/${encodeURIComponent(id)}/preview`, { method: "POST" }); refresh(); }
    catch (err) { say(err.message); }
  }

  async function remove(id, title) {
    if (!window.confirm(`Purge "${title}" from the audio bank?`)) return;
    try { await api(`/api/clips/${encodeURIComponent(id)}`, { method: "DELETE" }); say(`Purged ${title}.`, true); refresh(); }
    catch (err) { say(err.message); }
  }

  /* ---------------- status ---------------- */
  function setStat(id, cls, value) {
    const el = document.getElementById(id);
    el.classList.remove("is-live", "is-alert", "is-warm");
    if (cls) el.classList.add(cls);
    el.querySelector('[data-field]').textContent = value;
  }

  function renderState(state) {
    setStat("stat-magnet", state.magnet_present ? "is-live" : "is-warm",
      state.magnet_present ? "Seated" : "Lifted");
    setStat("stat-playback", state.playing ? "is-live" : "", state.playing ? "Speaking" : "Silent");
    setStat("stat-amp", state.amp_online ? "is-live" : "is-alert",
      state.amp_online ? "Online" : "No I2C");

    volumeMax = state.volume_max;
    if (!volumeDirty) { volume = state.volume; }
    paintVolume();

    state.jobs = state.jobs.filter((job) => !dismissed.has(job.id));
    renderClips(state);
  }

  let refreshing = false;
  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    try {
      renderState(await api("/api/state"));
      setField("link", window.location.host);
    } catch (err) {
      setStat("stat-amp", "is-alert", "Offline");
      setField("link", "link lost");
      void err;
    } finally {
      refreshing = false;
    }
  }

  /* ---------------- upload ---------------- */
  const drop = $("#drop");
  const fileInput = $("#file");

  $("#browse").addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => { upload(fileInput.files); fileInput.value = ""; });
  drop.addEventListener("submit", (e) => e.preventDefault());

  for (const type of ["dragenter", "dragover"]) {
    drop.addEventListener(type, (e) => { e.preventDefault(); drop.classList.add("is-over"); });
  }
  for (const type of ["dragleave", "drop"]) {
    drop.addEventListener(type, (e) => { e.preventDefault(); drop.classList.remove("is-over"); });
  }
  drop.addEventListener("drop", (e) => upload(e.dataTransfer.files));

  async function upload(files) {
    for (const file of files) {
      const form = new FormData();
      form.append("file", file);
      try {
        await api("/api/clips", { method: "POST", body: form });
        say(`Ingesting ${file.name}…`, true);
      } catch (err) {
        say(`${file.name}: ${err.message}`);
      }
    }
    refresh();
  }

  /* ---------------- synthesize ---------------- */
  const sayForm = $("#say");
  if (sayForm) {
    const sayText = $("#say-text");
    const sayVoice = $("#say-voice");
    const sayGo = $("#say-go");

    sayForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const text = sayText.value.trim();
      if (!text) { say("Nothing to say."); return; }

      sayGo.disabled = true;
      try {
        const result = await api("/api/speak", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, voice: sayVoice.value }),
        });
        say(`Synthesising "${result.title}"…`, true);
        sayText.value = "";
      } catch (err) {
        say(err.message);
      } finally {
        sayGo.disabled = false;
        refresh();
      }
    });

    // Ctrl/Cmd+Enter submits, the way a console would.
    sayText.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        sayForm.requestSubmit();
      }
    });
  }

  /* ---------------- manual controls ---------------- */
  $("#trigger").addEventListener("click", async () => {
    try { const r = await api("/api/trigger", { method: "POST" }); say(`Playing ${r.playing}.`, true); refresh(); }
    catch (err) { say(err.message); }
  });

  $("#halt").addEventListener("click", async () => {
    try { await api("/api/stop", { method: "POST" }); refresh(); }
    catch (err) { say(err.message); }
  });

  paintVolume();
  refresh();
  setInterval(refresh, 1000);
})();
