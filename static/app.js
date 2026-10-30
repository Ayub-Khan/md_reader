/* md_reader front-end */
"use strict";

const page = document.body.dataset.page;

/* ==========================================================================
   Library page — add / remove folders
   ========================================================================== */
if (page === "library") {
  const form = document.getElementById("add-form");
  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = form.querySelector("input[name=path]");
    const btn = form.querySelector("button[type=submit]");
    const val = input.value.trim();
    if (!val) return;
    btn.disabled = true;
    btn.textContent = "Adding…";
    try {
      const res = await fetch("/api/folders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: val }),
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.error || "Could not add folder.");
        btn.disabled = false;
        btn.textContent = "Add";
        return;
      }
      location.reload(); // refresh list + file counts
    } catch (err) {
      alert("Network error: " + err.message);
      btn.disabled = false;
      btn.textContent = "Add";
    }
  });

  // two-tap confirmation before removing
  document.querySelectorAll(".remove-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!btn.classList.contains("confirm")) {
        btn.classList.add("confirm");
        btn.textContent = "✕ Tap again";
        setTimeout(() => {
          btn.classList.remove("confirm");
          btn.textContent = "🗑";
        }, 2500);
        return;
      }
      const fid = btn.closest(".folder-card").dataset.fid;
      await fetch(`/api/folders/${fid}`, { method: "DELETE" });
      location.reload();
    });
  });
}

/* ==========================================================================
   Reader page — split into sections, drawer navigation, read-aloud
   ========================================================================== */
if (page === "read") {
  const reader = document.getElementById("reader");
  const drawer = document.getElementById("drawer");
  const drawerToggle = document.getElementById("drawer-toggle");
  const sectionList = document.getElementById("section-list");
  const drawerTitle = drawer.querySelector("h2");
  const ttsBar = document.getElementById("tts-bar");
  const ttsPlay = document.getElementById("tts-play");
  const ttsStatus = document.getElementById("tts-status");
  const rateInput = document.getElementById("rate");
  const rateVal = document.getElementById("rate-val");

  let sections = [];  // {heading, level, box, text}
  let curIdx = 0;

  /* ---------- organize document at h1–h3 boundaries ---------- */
  function initSections() {
    const children = Array.from(reader.children);
    let box = null;
    for (const el of children) {
      const isHeading = /^H[1-3]$/.test(el.tagName);
      if (isHeading || !box) {
        box = document.createElement("section");
        reader.insertBefore(box, el);
        sections.push({
          heading: isHeading ? el.textContent.trim() : "",
          level: isHeading ? Number(el.tagName[1]) : 1,
          box,
        });
      }
      box.appendChild(el); // heading and its content both go in
    }

    for (const s of sections) {
      const parts = [];
      for (const el of s.box.children) parts.push(el.innerText || "");
      s.text = ((s.heading ? s.heading + ". " : "") + parts.join(" "))
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 20000); // safety cap for very long sections
    }
    buildDrawer();
  }

  function buildDrawer() {
    sectionList.innerHTML = "";
    sections.forEach((s, i) => {
      const label = s.heading || "(beginning)";
      const li = document.createElement("li");
      li.className = "lvl" + s.level;

      const a = document.createElement("a");
      a.href = "#";
      a.title = label;
      const span = document.createElement("span");
      span.className = "sec-label";
      span.textContent = label;
      a.appendChild(span);
      a.addEventListener("click", (e) => {
        e.preventDefault();
        jumpTo(i);
        closeDrawer();
      });

      const play = document.createElement("button");
      play.className = "sec-play";
      play.textContent = "▶";
      play.setAttribute("aria-label", "Read section: " + label);
      play.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        closeDrawer();
        startPlayback(i);
      });

      li.appendChild(a);
      li.appendChild(play);
      sectionList.appendChild(li);
    });
  }

  /* ---------- navigation / highlight ---------- */
  function jumpTo(i) {
    if (sections[i]) {
      sections[i].box.scrollIntoView({ behavior: "smooth", block: "start" });
      setCurrent(i, false);
    }
  }
  function setCurrent(i, highlight) {
    sections.forEach((s, j) => {
      s.box.classList.toggle("current", highlight && j === i);
      sectionList.children[j]?.classList.toggle("active", j === i);
    });
    if (i >= 0 && i < sections.length) curIdx = i;
  }

  /* ---------- drawer open/close ---------- */
  function openDrawer() { drawer.hidden = false; }
  function closeDrawer() { drawer.hidden = true; }
  drawerToggle.addEventListener("click", () =>
    drawer.hidden ? openDrawer() : closeDrawer());
  drawerTitle?.addEventListener("click", closeDrawer);

  /* ==========================================================================
     Read aloud engine.

     Every button press bumps `session` and hard-stops all speech. Any old
     utterance callback first checks "am I still the live session?" — if not,
     it does nothing. This makes ⏮/⏭/⏸/✕ deterministic: no stale utterance
     can ever chain forward after you have given a new command.
     ========================================================================== */
  const TTS_SUPPORTED = "speechSynthesis" in window;
  let state = "idle";     // idle | playing | paused
  let session = 0;        // bumped on every command
  let utt = null;         // current utterance
  let uttStart = 0;       // absolute char offset where current utterance began
  let uttPos = 0;         // latest boundary position (relative to utterance)

  function setStatus(s) { ttsStatus.textContent = s; }

  function detachUtt() {
    if (!utt) return;
    utt.onend = utt.onerror = utt.onboundary = null;
    utt = null;
  }

  function hardStop() {
    detachUtt();
    try { speechSynthesis.cancel(); } catch (_) {}
  }

  /* speakAt must only be reached right after a session bump (or from a live
     session's own onend chain, which keeps the same token). */
  function speakAt(i, from) {
    const my = session;
    const s = sections[i];
    if (!s) { finish(); return; }
    setCurrent(i, true);
    uttStart = from;
    uttPos = 0;
    const text = s.text.slice(from).trim() || s.heading || "…";
    setStatus((s.heading || "Section " + (i + 1)).slice(0, 42));
    const u = new SpeechSynthesisUtterance(text);
    u.rate = Number(rateInput.value);
    u.onboundary = (e) => {
      if (my === session) uttPos = e.charIndex;
    };
    u.onend = () => {
      if (my !== session || state !== "playing") return; // stale — ignore
      detachUtt();
      speakAt(i + 1, 0);
    };
    u.onerror = (e) => {
      if (my !== session || state !== "playing") return;
      detachUtt();
      if (e?.error === "interrupted" || e?.error === "canceled") return;
      speakAt(i, from); // transient engine error → retry section once
    };
    utt = u;
    // Chrome needs a beat between cancel() and speak() or it drops utterances
    setTimeout(() => {
      if (my === session && utt === u) {
        try { speechSynthesis.speak(u); } catch (_) {}
      }
    }, 60);
  }

  function commandEnter() {
    session++;
    hardStop();
  }

  function showPlaying() {
    state = "playing";
    ttsBar.hidden = false;
    ttsPlay.textContent = "⏸";
  }

  function startPlayback(i) {
    if (!TTS_SUPPORTED || !sections.length) return;
    commandEnter();
    showPlaying();
    speakAt(Math.min(Math.max(i, 0), sections.length - 1), 0);
  }

  function pausePlayback() {
    state = "paused";          // set BEFORE hardStop so onend sees "paused"
    session++;
    hardStop();
    setStatus("Paused");
    ttsPlay.textContent = "▶";
  }

  function resumePlayback() {
    const s = sections[curIdx];
    if (!s) { finish(); return; }
    const from = uttStart + uttPos;
    commandEnter();
    if (from >= s.text.length) { showPlaying(); speakAt(curIdx + 1, 0); return; }
    showPlaying();
    setStatus("Reading…");
    speakAt(curIdx, from);
  }

  function finish() {
    commandEnter();
    state = "idle";
    ttsPlay.textContent = "▶";
    setStatus("Finished");
    setCurrent(-1, false);
  }

  ttsPlay.addEventListener("click", () => {
    if (state === "playing") pausePlayback();
    else if (state === "paused") resumePlayback();
    else startPlayback(curIdx); // idle → continue (or begin) at current pos
  });

  function skip(dir) {
    const target = curIdx + dir;
    commandEnter();
    if (target < 0) { showPlaying(); speakAt(0, 0); return; }
    if (target >= sections.length) { state = "idle"; setStatus("Finished"); return; }
    showPlaying();
    speakAt(target, 0);
  }
  document.getElementById("tts-next").addEventListener("click", () => skip(1));
  document.getElementById("tts-prev").addEventListener("click", () => skip(-1));
  document.getElementById("tts-close").addEventListener("click", () => {
    finish();
    ttsBar.hidden = true;
    setStatus("Idle");
  });
  rateInput.addEventListener("input", () => {
    rateVal.textContent = Number(rateInput.value).toFixed(1) + "×";
    if (utt) utt.rate = Number(rateInput.value);
  });

  /* ---------- init ---------- */
  initSections();
  setCurrent(0, false);

  // graceful fallback when the browser has no speech engine
  if (!TTS_SUPPORTED) {
    ttsBar.hidden = true;
    document.querySelectorAll(".sec-play").forEach((b) => (b.disabled = true));
    if (drawerTitle) drawerTitle.textContent = "Sections (audio unavailable)";
    document.getElementById("drawer-prefs").hidden = true;
  }
}
