#!/usr/bin/env python3
"""
md_reader — read local Markdown files from your phone.

Run:  python app.py [folders to register ...] [--port N]

Serves a mobile-friendly reader on your LAN. Scan the printed QR code
with your phone, browse folders, and use the built-in read-aloud controls
(phone's native text-to-speech, works offline).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import socket
import sys
from pathlib import Path
from urllib.parse import quote, unquote

import markdown as md
import qrcode
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "library.json"
STATIC_DIR = APP_DIR / "static"
COOKIE = "mdr_key"

IGNORED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv",
    "__pycache__", ".obsidian", ".idea", ".vscode", ".tox",
}
MAX_FILE_BYTES = 2_000_000


# --------------------------------------------------------------------------
# configuration ("library" = list of markdown folders)
# --------------------------------------------------------------------------
def load_config() -> dict:
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            cfg = {}
    cfg.setdefault("port", 8000)
    cfg.setdefault("token", secrets.token_urlsafe(16))
    cfg.setdefault("folders", [])
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")


CFG = load_config()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def folder_id(path: str) -> str:
    return hashlib.sha1(path.encode()).hexdigest()[:10]


def real_subpath(folder_path: str, relpath: str) -> Path | None:
    """Resolve relpath under folder_path safely (no ../ escapes)."""
    base = Path(folder_path).resolve()
    candidate = (base / unquote(relpath)).resolve()
    if candidate == base or base not in candidate.parents:
        return None
    return candidate


def list_markdown(folder_path: str) -> list[dict]:
    """All .md/.markdown files in the folder, sorted, with subdir labels."""
    base = Path(folder_path)
    files = []
    for p in base.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in (".md", ".markdown"):
            continue
        rel = p.relative_to(base)
        if any(part in IGNORED_DIRS for part in rel.parts[:-1]):
            continue
        files.append({
            "rel": str(rel),
            "name": p.stem,
            "dir": str(rel.parent) if len(rel.parts) > 1 else "",
            "size": p.stat().st_size,
        })
    files.sort(key=lambda f: (f["dir"].lower(), f["name"].lower()))
    return files


def folder_stats(folder: dict) -> tuple[int, int]:
    n_files = 0
    n_bytes = 0
    for f in list_markdown(folder["path"]):
        n_files += 1
        n_bytes += f["size"]
    return n_files, n_bytes


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def localhost_name() -> None:
    pass  # kept for clarity of intent; unused


def get_lan_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def alt_title(text: str, filename: str) -> str:
    for line in text.splitlines()[:20]:
        if line.lstrip().startswith("#"):
            return line.lstrip().lstrip("#").strip()
    return filename


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------
def authed(request: Request) -> bool:
    return request.cookies.get(COOKIE) == CFG["token"]


def deny(request: Request) -> HTMLResponse:
    ip = get_lan_ip() or "this-machine"
    port = CFG["port"]
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;background:#111;color:#eee;"
        "padding:2rem;text-align:center'>"
        "<h2>&#128274; Access key required</h2>"
        f"<p>Visit <b>http://{ip}:{port}/</b> and scan the QR code shown on "
        "the laptop, or open this app again with the key link.</p></body>",
        status_code=403,
    )


# --------------------------------------------------------------------------
# page templates
# --------------------------------------------------------------------------
def page(title: str, body: str, page_name: str, status: int = 200) -> HTMLResponse:
    html = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="/static/style.css">
<link rel="stylesheet" href="/static/pygments.css">
</head><body data-page="{page_name}">
{body}
<script src="/static/app.js" defer></script>
</body></html>"""
    return HTMLResponse(html, status_code=status)


def not_found_page(message: str) -> HTMLResponse:
    return page(
        "Not found",
        f"<main><p class='empty'>{message}</p>"
        "<p><a class='linkback' href='/library'>&larr; Library</a></p></main>",
        "folder",
        status=404,
    )


def library_page() -> HTMLResponse:
    rows = ""
    for f in CFG["folders"]:
        n_files, n_bytes = folder_stats(f)
        rows += f"""
<article class="card folder-card" data-fid="{f["fid"]}">
  <a class="folder-link" href="/folder/{f["fid"]}">
    <span class="folder-name">&#128193; {f["name"]}</span>
    <span class="folder-meta">{n_files} files &middot; {human_size(n_bytes)}</span>
    <span class="folder-path">{f["path"]}</span>
  </a>
  <button class="icon-btn remove-btn" title="Remove folder"
          aria-label="Remove {f["name"]}">&#128465;</button>
</article>"""
    if not CFG["folders"]:
        rows = ("<p class='empty'>No folders yet. Add one below, or run "
                "<code>python app.py /path/to/notes</code> on the laptop.</p>")

    body = f"""
<header class="topbar">
  <h1>&#128214; md_reader</h1>
  <p class="sub">Your markdown library</p>
</header>
<main>
  <section>{rows}</section>
  <details class="card add-card"><summary>&#10133; Add a folder</summary>
    <form id="add-form">
      <input type="text" name="path" placeholder="/home/user/notes"
             autocomplete="off" autocapitalize="off" spellcheck="false">
      <button type="submit">Add</button>
    </form>
    <p class="hint">Absolute path on the laptop. Hidden folders like
       .git are skipped.</p>
  </details>
</main>"""
    return page("Library &middot; md_reader", body, "library")


def browse_page(fid: str, relpath: str) -> HTMLResponse:
    folder = next((f for f in CFG["folders"] if f["fid"] == fid), None)
    if folder is None:
        return not_found_page("Unknown folder.")
    base = Path(folder["path"]).resolve()
    cur = base
    if relpath:
        cur = real_subpath(folder["path"], relpath)
        if cur is None or not cur.is_dir():
            return not_found_page("Folder not found.")

    dirs = sorted(
        (p for p in cur.iterdir()
         if p.is_dir() and not p.name.startswith(".") and p.name not in IGNORED_DIRS),
        key=lambda p: p.name.lower(),
    )
    files = sorted(
        (p for p in cur.iterdir()
         if p.is_file() and p.suffix.lower() in (".md", ".markdown")),
        key=lambda p: p.name.lower(),
    )

    rel_cur = "" if cur == base else str(cur.relative_to(base))

    items = ""
    for d_ in dirs:
        rel_link = str(Path(rel_cur) / d_.name) if rel_cur else d_.name
        items += f"""
<li><a class="row row-dir" href="/folder/{fid}?d={quote(rel_link, safe='')}">
  <span class="doc-name"><span class="src">&#128449;</span> {d_.name}/</span>
  <span class="chev">&#8250;</span>
</a></li>"""
    for f_ in files:
        rel_link = str(Path(rel_cur) / f_.name) if rel_cur else f_.name
        items += f"""
<li><a class="row row-file" href="/read/{fid}?f={quote(rel_link, safe='')}">
  <span class="doc-name"><span class="src">&#128196;</span> {f_.stem}</span>
  <span class="doc-size">{human_size(f_.stat().st_size)}</span>
</a></li>"""
    if not dirs and not files:
        items = "<li class='empty'>Nothing here.</li>"

    # breadcrumb: Library / root-name / sub / parts...
    parts = [x for x in Path(rel_cur).parts] if rel_cur else []
    crumbs = f"<a class='crumb' href='/library'>&larr; Library</a>" \
             f"<span class='bc-strut'></span><a class='crumb' href='/folder/{fid}'><b>{folder['name']}</b></a>"
    acc = ""
    for part in parts:
        acc = str(Path(acc) / part) if acc else part
        crumbs += f" <span class='bc-sep'>&rsaquo;</span> <a class='crumb' href=\"/folder/{fid}?d={quote(acc, safe='')}\">{part}</a>"

    body = f"""
<header class="topbar"><nav class="bc">{crumbs}</nav></header>
<main><ul class="doc-list">{items}</ul></main>"""
    return page(f"{folder['name']} &middot; md_reader", body, "folder")


def reader_page(fid: str, relpath: str) -> HTMLResponse:
    folder = next((f for f in CFG["folders"] if f["fid"] == fid), None)
    if folder is None:
        return not_found_page("Unknown folder.")
    path = real_subpath(folder["path"], relpath)
    if path is None or not path.is_file() or path.suffix.lower() not in \
            (".md", ".markdown"):
        return not_found_page("File not found.")
    text = path.read_text(errors="replace")[:MAX_FILE_BYTES]
    content_html = md.markdown(
        text,
        extensions=["fenced_code", "codehilite", "tables", "toc", "sane_lists"],
        extension_configs={"codehilite": {"guess_lang": False}},
    )
    title = alt_title(text, path.stem)

    files = list_markdown(folder["path"])
    rels = [f["rel"] for f in files]
    idx = rels.index(str(path.relative_to(folder["path"])))
    prev_link = next_link = ""
    if idx > 0:
        p = files[idx - 1]
        prev_link = (f"<a href='/read/{fid}?f={quote(p['rel'], safe='')}' "
                     f"title='{p['name']}'>&larr; Prev</a>")
    if idx < len(files) - 1:
        n = files[idx + 1]
        next_link = (f"<a href='/read/{fid}?f={quote(n['rel'], safe='')}' "
                     f"title='{n['name']}'>Next &rarr;</a>")

    body = f"""
<header class="topbar reader-topbar">
  <a class="crumb" href="/folder/{fid}">&larr; {folder["name"]}</a>
  <div class="prevnext">{prev_link} {next_link}</div>
</header>
<article class="reader" id="reader" data-file="{path.name}">{content_html}</article>

<button id="drawer-toggle" aria-label="Sections and audio">&#9776; Sections</button>
<nav id="drawer" hidden>
  <h2>Sections</h2>
  <ul id="section-list"></ul>
  <div id="drawer-prefs" class="drawer-prefs">
    <label>Voice speed
      <input id="rate" type="range" min="0.6" max="2" step="0.1" value="1">
      <span id="rate-val">1.0&times;</span>
    </label>
  </div>
</nav>

<div id="tts-bar" hidden>
  <button id="tts-prev" aria-label="Previous section">&#9198;</button>
  <button id="tts-play" aria-label="Play">&#9654;</button>
  <button id="tts-next" aria-label="Next section">&#9197;</button>
  <span id="tts-status" role="status">Idle</span>
  <button id="tts-close" aria-label="Stop audio">&#10005;</button>
</div>
"""
    return page(f"{title} &middot; md_reader", body, "read")


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
app = FastAPI(title="md_reader", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def root(key: str = ""):
    if key and key == CFG["token"]:
        resp = RedirectResponse("/library", status_code=303)
        resp.set_cookie(COOKIE, key, max_age=30 * 24 * 3600,
                        httponly=True, samesite="lax")
        return resp
    return deny  # 403 with guidance


@app.get("/library")
def library(request: Request):
    if not authed(request):
        return deny(request)
    return library_page()


@app.post("/api/folders")
async def add_folder(request: Request):
    if not authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=403)
    data = await request.json()
    raw = str(data.get("path", "")).strip()
    if not raw:
        return JSONResponse({"error": "Path is empty."}, status_code=400)
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        return JSONResponse(
            {"error": f"'{raw}' is not a folder on the laptop."}, status_code=400)
    entry = {"fid": folder_id(str(path)), "name": path.name or str(path),
             "path": str(path)}
    if any(f["path"] == entry["path"] for f in CFG["folders"]):
        return JSONResponse({"error": "Already in your library."}, status_code=400)
    CFG["folders"].append(entry)
    save_config(CFG)
    return JSONResponse({"ok": True, "folder": entry})


@app.delete("/api/folders/{fid}")
def remove_folder(fid: str, request: Request):
    if not authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=403)
    before = len(CFG["folders"])
    CFG["folders"] = [f for f in CFG["folders"] if f["fid"] != fid]
    if len(CFG["folders"]) == before:
        return JSONResponse({"error": "Unknown folder."}, status_code=404)
    save_config(CFG)
    return JSONResponse({"ok": True})


@app.get("/folder/{fid}")
def folder(fid: str, request: Request, d: str = ""):
    if not authed(request):
        return deny(request)
    return browse_page(fid, d)


@app.get("/read/{fid}")
def read_file(fid: str, request: Request, f: str = ""):
    if not authed(request):
        return deny(request)
    return reader_page(fid, f)


# --------------------------------------------------------------------------
# startup
# --------------------------------------------------------------------------
def banner(port: int) -> None:
    ip = get_lan_ip()
    url = f"http://{ip}:{port}/?key={CFG['token']}" if ip else \
          f"http://localhost:{port}/?key={CFG['token']}"
    print("=" * 56)
    print("  md_reader is running")
    print(f"  Laptop:   http://localhost:{port}/")
    print(f"  Phone:    {url}")
    print("  Scan with your phone camera:")
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.print_ascii(invert=True)
    print("=" * 56)


def register_folders_from_cli(paths: list[str]) -> None:
    for raw in paths:
        path = Path(raw).expanduser().resolve()
        if not path.is_dir():
            print(f"  ! skipping '{raw}' (not a folder)")
            continue
        entry = {"fid": folder_id(str(path)), "name": path.name or str(path),
                 "path": str(path)}
        if any(f["path"] == entry["path"] for f in CFG["folders"]):
            print(f"  = already registered: {entry['path']}")
            continue
        CFG["folders"].append(entry)
        print(f"  + registered: {entry['path']}")
    save_config(CFG)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read local markdown on your phone")
    parser.add_argument("folders", nargs="*", help="folders to register")
    parser.add_argument("-p", "--port", type=int, default=CFG["port"])
    args = parser.parse_args()

    if args.folders:
        register_folders_from_cli(args.folders)
    if not CFG["folders"]:
        here = str(Path.cwd().resolve())
        print(f"  no folders configured; registering current dir: {here}")
        register_folders_from_cli([here])

    if args.port != CFG["port"]:
        CFG["port"] = args.port
        save_config(CFG)

    banner(args.port)
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
