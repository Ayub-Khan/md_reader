# 📚 md_reader

> A pocket reader for the markdown files rotting quietly in your laptop's
> folders — built for lazy people like me who want to read their massive
> docs on the phone instead of squinting at an IDE.

## What this does

You have a system full of `.md` files. Your notes, project docs, architecture
rambles, trading-system write-ups. Opening them on the laptop when you're not
at the laptop is annoying — and honestly, reading markdown files straight in
the native Claude app or an editor on a phone is a bit *so-so*. No file tree,
cramped viewing, nothing to navigate long documents with.

**md_reader** is the edge you want:

- Run a tiny server on your laptop → scan a QR code with your phone → all your
  markdown is now a clean, navigable, phone-sized library.

## Features

### 🌳 Real file-tree browsing (like your IDE)
The one feature that makes massive doc folders usable: sub-folders are shown
first, **tap to drill in** level by level, and a breadcrumb trail
(`Library › psx-trading-system › docs`) jumps you back up. No endless
flat list of everything-not-a-readme.

### 🧭 Section navigation for long documents
Every document gets a "☰ Sections" drawer built from its H1–H3 headings.
Tap to jump anywhere in the document. No more thumb-scrolling through 4,000
lines to find *the* section.

### 🔊 Read-aloud, controlled properly
Phone's native text-to-speech (offline, free, no API keys):

- ▶ per-section play, or auto-advance like an audiobook
- ⏮ / ⏭ jump one section at a time
- Pause remembers the **exact word** where you stopped and resumes from there
- Speed slider: 0.6×–2×
- Engine is restart-proof across Android Chrome / iOS Safari quirks: every
  button press is boss, and no stale audio can chain-forward behind your back

### 🎨 Actually pleasant rendering
Blue H1 → purple H2 → cyan H3 heading tiers, tinted callouts, striped tables,
colored list markers, and **syntax-highlighted** fenced code blocks (nord
theme). Dark theme, mobile-first, thumbs-sized tapping targets.

### 📚 Multiple libraries
Register as many folders as you want — from the laptop terminal at startup
*or* by typing a path directly in the phone UI. Removing takes two taps
(safety against fat fingers).

### 🔐 Locked to you, not the whole Wi‑Fi
A random access token is baked into the QR code URL. Anybody without the key
gets a polite 403. Files can't be reached outside registered folders
(path traversal is blocked in tests).

## What it is *not*

- Not a sync service — the phone streams from the laptop over your network
- Not a web app with accounts — one URL with one key is the whole login
- Not an Obsidian replacement — it's a reader (obsidian-style `[[wikilinks]]`
  is on the maybe-someday list)

## Quick start

```bash
git clone https://github.com/<you>/md_reader.git
cd md_reader
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# one or more folders to serve, then scan the QR printed in the terminal
.venv/bin/python app.py ~/notes ~/work/docs
```

The terminal shows a QR code + URL like `http://192.168.x.x:8000/?key=…`.
Scan it; the key is saved as a 30-day cookie. From then on:

```bash
.venv/bin/python app.py        # serves previously registered folders
.venv/bin/python app.py -p 9000
```

## Using the reader

- **Library page** — tap 📚 folders, ➕ Add a folder (absolute path on the
  laptop, e.g. `/home/ayub/notes`), 🗑 to remove (two taps to confirm)
- **Explorer tree** — folders first, tap to go deeper, breadcrumb to go back
- **☰ Sections** — tap a row to jump, ▶ to read that section aloud
- **Audio bar** — ▶/⏸ play or pause, ⏮/⏭ to move a section, ✕ to stop
  and hide the bar; auto-advance reads sections one after another

## Files

| Path | Purpose |
|---|---|
| `app.py` | Server, routes, pages, QR banner, auth |
| `static/style.css` | Mobile-first dark styles + color tiers |
| `static/app.js` | File-tree rendering helpers, section splitter, speech engine |
| `static/pygments.css` | nord colors for code blocks |
| `library.json` | Saved folders, port, access token (auto-created) |

## Notes & limitations

- Phone and laptop must share the same network (standard LAN setup)
- Only `.md` / `.markdown` files are listed; hidden dirs like `.git` and
  `.venv` are skipped
- Very large files are capped at 2 MB of text
- Local image links inside markdown aren't served (text-first v1)
- Lost your phone's access? Delete `library.json` and restart — fresh token

## Ideas for later

- Serve images/attachments referenced by notes
- Obsidian-style wikilinks (`[[notes]]`) resolved between documents
- Desktop shortcut: start server and show the QR in one double-click
- Voice/language picker for TTS
- light mode for daytime

---

**For** people with more folders than motivation. **Because** the docs you
actually wrote deserve a better bedside reading experience than a terminal
vi session at 1 a.m.
