"""The layout builder's page, and the one-off server that hands it to a browser.

A design-time tool, so it is a browser rather than a screen: dragging a grid into
shape with a mouse is a thing browsers already do well and a terminal does badly.
Everything about the server follows from it being open for as long as somebody is
arranging a menu and not one second longer.

- **`127.0.0.1` on an ephemeral port**, so nothing on the network can reach it.
- **A single-use token on every request**, because localhost is not a boundary: any
  program on this machine can reach a loopback port, and any page in the browser
  can POST to one. Without the token every path answers 404, which is also what a
  wrong token gets - a 403 confirms the path.
- **Assets from a dict, never from the filesystem**, so there is no path to
  traverse. The page is a constant here for the same reason `handover.py`'s script
  is: it ships as program text rather than as a file the build has to remember.
- **Nothing is written by the server.** It hands back a document; saving it is the
  capability's, through `ConfigPort` like every other setting.

See `docs/decisions/0007`.
"""

import asyncio
import json
import secrets
import threading
from collections.abc import Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from company_tui.domain.layout import Layout, read_layout, write_layout

HOST = "127.0.0.1"
MAX_BODY = 256 * 1024
"""A layout is a page of settings. Anything past this is not one."""

DRAIN_LIMIT = 4 * MAX_BODY
"""How much of a refused body is read away before the connection is dropped instead."""

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Layout</title>
<link rel="stylesheet" href="builder.css?t=TOKEN">
</head>
<body>
<header class="bar">
  <div class="mark"></div>
  <div>
    <h1>Layout</h1>
    <p class="sub">Colours, window and menu. Saved into your settings file.</p>
  </div>
  <div class="grow"></div>
  <span class="said" id="said"></span>
  <button class="ghost" id="reset" type="button">Reset</button>
  <button class="go" id="save" type="button">Save and close</button>
</header>

<main>
  <section class="pane">
    <h2>Menu</h2>
    <p class="hint">Drag to reorder. The numbers follow the order you leave them in.
       Untick to leave one off the menu; you cannot leave them all off.</p>
    <ul id="cards" class="cards"></ul>

    <label class="row"><span>Cards per row</span>
      <input id="across" type="range" min="1" max="6" step="1">
      <output id="acrossOut"></output>
    </label>

    <h2>Window</h2>
    <p class="hint">Pixels. The interface opens at the first pair and is held to the
       second. Taken up the next time the app starts.</p>
    <div class="sizes" id="sizes"></div>

    <h2>Colours</h2>
    <p class="hint">Every one of these is a theme token the interface draws from.</p>
    <div class="swatches" id="swatches"></div>
  </section>

  <section class="pane preview">
    <h2>Preview</h2>
    <div class="frame" id="frame">
      <div class="frameHead">
        <div class="logo">&#9650;</div>
        <div>
          <div class="app" id="pvName">DTI</div>
          <div class="tag">Developer Toolbox</div>
        </div>
        <div class="grow"></div>
        <div class="ver">workspace ready</div>
      </div>
      <div class="frameBody">
        <div class="pvTitle">What would you like to do?</div>
        <div class="pvSub">Choose a workflow to get started.</div>
        <div class="grid" id="pvGrid"></div>
      </div>
      <div class="frameFoot">
        <span class="key">Enter</span> Select
        <span class="key">Esc</span> Quit
      </div>
    </div>
    <p class="hint" id="problems"></p>
  </section>
</main>
<script src="builder.js?t=TOKEN"></script>
</body>
</html>
"""

STYLE = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; font: 14px/1.5 ui-sans-serif, system-ui, sans-serif;
  background: #0b1016; color: #e6edf5;
}
.bar {
  display: flex; align-items: center; gap: 14px; padding: 14px 22px;
  border-bottom: 1px solid #1d2a38; position: sticky; top: 0; background: #0b1016;
}
.bar h1 { font-size: 16px; margin: 0; }
.sub, .hint { color: #8ba0b6; font-size: 12px; margin: 2px 0 0; }
.hint { margin: 0 0 12px; }
.mark { width: 22px; height: 22px; border-radius: 5px; background: #e3a857; }
.grow { flex: 1; }
.said { color: #8ba0b6; font-size: 12px; }
button {
  font: inherit; border-radius: 7px; padding: 7px 14px; cursor: pointer;
  border: 1px solid #2a3b4e; background: #121c26; color: #e6edf5;
}
button.go { background: #e3a857; border-color: #e3a857; color: #10202f; font-weight: 600; }
button:hover { border-color: #e3a857; }
main { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 18px; padding: 18px 22px 40px; }
@media (max-width: 900px) { main { grid-template-columns: minmax(0, 1fr); } }
.pane { background: #0f1720; border: 1px solid #1d2a38; border-radius: 12px; padding: 18px; }
.pane h2 { font-size: 13px; letter-spacing: .08em; text-transform: uppercase;
           color: #8ba0b6; margin: 22px 0 6px; }
.pane h2:first-child { margin-top: 0; }
.cards { list-style: none; margin: 0 0 18px; padding: 0; display: grid; gap: 8px; }
.cards li {
  display: flex; align-items: center; gap: 10px; padding: 10px 12px; cursor: grab;
  background: #121c26; border: 1px solid #22303f; border-radius: 9px;
}
.cards li.drag { opacity: .35; }
.cards li.over { border-color: #e3a857; }
.cards li.off .who { opacity: .4; text-decoration: line-through; }
.handle { color: #5b7188; letter-spacing: 2px; }
.who { flex: 1; min-width: 0; }
.who b { display: block; font-weight: 600; }
.who span { color: #8ba0b6; font-size: 12px; display: block;
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row { display: flex; align-items: center; gap: 12px; margin: 10px 0 0; }
.row span { width: 120px; color: #8ba0b6; font-size: 12px; }
input[type=range] { flex: 1; accent-color: #e3a857; }
.sizes { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.sizes label { display: grid; gap: 4px; color: #8ba0b6; font-size: 12px; }
.sizes input {
  font: inherit; padding: 7px 9px; border-radius: 7px;
  border: 1px solid #2a3b4e; background: #0b1016; color: #e6edf5;
}
.swatches { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.swatch { display: flex; align-items: center; gap: 9px; background: #121c26;
          border: 1px solid #22303f; border-radius: 9px; padding: 8px 10px; }
.swatch input { width: 30px; height: 30px; padding: 0; border: none; background: none; cursor: pointer; }
.swatch span { font-size: 12px; color: #8ba0b6; }
.frame { border: 1px solid; border-radius: 10px; overflow: hidden; font-family: ui-monospace, monospace; }
.frameHead { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-bottom: 1px solid; }
.logo { font-size: 18px; }
.app { font-weight: 700; letter-spacing: .12em; }
.tag, .ver { font-size: 11px; opacity: .75; }
.frameBody { padding: 16px 14px 20px; }
.pvTitle { font-weight: 700; margin-bottom: 2px; }
.pvSub { font-size: 12px; opacity: .7; margin-bottom: 14px; }
.grid { display: grid; gap: 9px; }
.card { border: 1px solid; border-radius: 7px; padding: 9px 11px; font-size: 12px; }
.card b { display: block; font-size: 12px; }
.card i { font-style: normal; opacity: .65; font-size: 11px; }
.card.first { border-width: 2px; }
.frameFoot { padding: 9px 14px; border-top: 1px solid; font-size: 11px; opacity: .8; }
.key { font-weight: 700; margin-left: 10px; }
.key:first-child { margin-left: 0; }
"""

SCRIPT = """
const token = new URLSearchParams(location.search).get("t") || "";
const url = (path) => path + "?t=" + encodeURIComponent(token);
const $ = (id) => document.getElementById(id);

let state = null;
let known = [];

const say = (text) => { $("said").textContent = text; };

async function load() {
  const answer = await fetch(url("/layout"));
  const body = await answer.json();
  state = body.layout;
  known = body.capabilities;
  draw();
}

function ordered() {
  const keys = known.map((one) => one.key);
  const wanted = (state.menu.order || []).filter((k) => keys.includes(k));
  keys.forEach((k) => { if (!wanted.includes(k)) wanted.push(k); });
  return wanted.map((k) => known.find((one) => one.key === k));
}

function shown() {
  const off = state.menu.hidden || [];
  const on = ordered().filter((one) => !off.includes(one.key));
  return on.length ? on : ordered();
}

function draw() {
  drawCards();
  drawSizes();
  drawSwatches();
  $("across").value = state.menu.cards_per_row;
  $("acrossOut").textContent = state.menu.cards_per_row;
  drawPreview();
}

function drawCards() {
  const list = $("cards");
  list.textContent = "";
  ordered().forEach((one) => {
    const off = (state.menu.hidden || []).includes(one.key);
    const row = document.createElement("li");
    row.draggable = true;
    row.dataset.key = one.key;
    if (off) row.classList.add("off");

    const grip = document.createElement("span");
    grip.className = "handle";
    grip.textContent = "::";

    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = !off;
    box.addEventListener("change", () => toggle(one.key));

    const who = document.createElement("div");
    who.className = "who";
    const name = document.createElement("b");
    name.textContent = one.name;
    const what = document.createElement("span");
    what.textContent = one.description;
    who.append(name, what);

    row.append(grip, box, who);
    wire(row);
    list.append(row);
  });
}

let dragging = null;

function wire(row) {
  row.addEventListener("dragstart", () => { dragging = row; row.classList.add("drag"); });
  row.addEventListener("dragend", () => {
    row.classList.remove("drag");
    document.querySelectorAll(".over").forEach((n) => n.classList.remove("over"));
    dragging = null;
    state.menu.order = [...$("cards").children].map((n) => n.dataset.key);
    changed();
  });
  row.addEventListener("dragover", (event) => {
    event.preventDefault();
    if (!dragging || dragging === row) return;
    row.classList.add("over");
    const box = row.getBoundingClientRect();
    const below = event.clientY - box.top > box.height / 2;
    row.parentNode.insertBefore(dragging, below ? row.nextSibling : row);
  });
  row.addEventListener("dragleave", () => row.classList.remove("over"));
}

function toggle(key) {
  const off = new Set(state.menu.hidden || []);
  if (off.has(key)) { off.delete(key); } else { off.add(key); }
  if (off.size >= known.length) { say("At least one card has to stay."); return; }
  state.menu.hidden = [...off];
  drawCards();
  drawPreview();
  changed();
}

function drawSizes() {
  const holder = $("sizes");
  holder.textContent = "";
  [["start_width", "Opens at (w)"], ["start_height", "Opens at (h)"],
   ["min_width", "No smaller than (w)"], ["min_height", "No smaller than (h)"]]
    .forEach(([key, label]) => {
      const wrap = document.createElement("label");
      const text = document.createElement("span");
      text.textContent = label;
      const field = document.createElement("input");
      field.type = "number";
      field.min = 320; field.max = 10000; field.step = 10;
      field.value = state.window[key];
      field.addEventListener("change", () => {
        state.window[key] = parseInt(field.value, 10) || state.window[key];
        changed();
      });
      wrap.append(text, field);
      holder.append(wrap);
    });
}

function drawSwatches() {
  const holder = $("swatches");
  holder.textContent = "";
  Object.keys(state.palette).forEach((key) => {
    const cell = document.createElement("div");
    cell.className = "swatch";
    const pick = document.createElement("input");
    pick.type = "color";
    pick.value = state.palette[key];
    pick.addEventListener("input", () => {
      state.palette[key] = pick.value;
      drawPreview();
    });
    pick.addEventListener("change", changed);
    const name = document.createElement("span");
    name.textContent = key;
    cell.append(pick, name);
    holder.append(cell);
  });
}

function drawPreview() {
  const paint = state.palette;
  const frame = $("frame");
  frame.style.background = paint.background;
  frame.style.color = paint.foreground;
  frame.style.borderColor = paint.primary;
  frame.querySelector(".frameHead").style.borderColor = paint.primary;
  frame.querySelector(".frameHead").style.background = paint.surface;
  frame.querySelector(".frameFoot").style.borderColor = paint.primary;
  frame.querySelector(".logo").style.color = paint.accent;

  const grid = $("pvGrid");
  grid.style.gridTemplateColumns = "repeat(" + state.menu.cards_per_row + ", minmax(0, 1fr))";
  grid.textContent = "";
  shown().forEach((one, index) => {
    const card = document.createElement("div");
    card.className = "card" + (index === 0 ? " first" : "");
    card.style.background = paint.panel;
    card.style.borderColor = index === 0 ? paint.accent : paint.secondary;
    const name = document.createElement("b");
    name.textContent = "[" + String(index + 1).padStart(2, "0") + "] " + one.name;
    const what = document.createElement("i");
    what.textContent = one.description;
    card.append(name, what);
    grid.append(card);
  });
}

async function changed() {
  const answer = await fetch(url("/layout"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state),
  });
  const body = await answer.json();
  $("problems").textContent = (body.problems || []).join("  -  ");
  say(body.problems && body.problems.length ? "Some of that was not taken." : "Held.");
}

$("across").addEventListener("input", (event) => {
  state.menu.cards_per_row = parseInt(event.target.value, 10);
  $("acrossOut").textContent = state.menu.cards_per_row;
  drawPreview();
});
$("across").addEventListener("change", changed);

$("reset").addEventListener("click", async () => {
  await fetch(url("/reset"), { method: "POST" });
  await load();
  say("Back to the defaults.");
});

$("save").addEventListener("click", async () => {
  await changed();
  await fetch(url("/done"), { method: "POST" });
  say("Saved. You can close this tab.");
  $("save").disabled = true;
});

load();
"""


class BuilderServer:
    """One page, on this machine, for as long as somebody is arranging a layout."""

    def __init__(
        self,
        layout: Layout,
        capabilities: Sequence[tuple[str, str, str]],
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._held = layout
        self._capabilities = tuple(capabilities)
        self._token = secrets.token_urlsafe(32)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._loop = loop
        self.finished = asyncio.Event()
        self.problems: tuple[str, ...] = ()

    @property
    def layout(self) -> Layout:
        """What the page has arranged so far, valid at every moment in between."""
        return self._held

    def start(self) -> str:
        """Open the port and return the one URL that answers on it."""
        self._server = ThreadingHTTPServer((HOST, 0), self._handler())
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        host, port = self._server.server_address[0], self._server.server_address[1]
        return f"http://{host}:{port}/?t={self._token}"

    def stop(self) -> None:
        """Close the port. Nothing about this outlives the run that opened it."""
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _done(self) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self.finished.set)
        else:
            self.finished.set()

    def _take(self, document: Any) -> tuple[str, ...]:
        self._held, problems = read_layout(document, self._held)
        self.problems = problems
        return problems

    def _assets(self) -> dict[str, tuple[str, bytes]]:
        page = PAGE.replace("TOKEN", self._token)
        return {
            "/": ("text/html; charset=utf-8", page.encode("utf-8")),
            "/builder.css": ("text/css; charset=utf-8", STYLE.encode("utf-8")),
            "/builder.js": ("text/javascript; charset=utf-8", SCRIPT.encode("utf-8")),
        }

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        outer = self
        assets = self._assets()

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args: Any) -> None:
                """Silence. The terminal belongs to the interface, not to this."""

            def _allowed(self) -> str:
                """The path, or `""` for anything without this run's token.

                The caller answers 404 to an empty one rather than 403, because a
                refusal that names the path confirms the path.
                """
                path, _, query = self.path.partition("?")
                fields = {}
                for pair in query.split("&"):
                    key, _, value = pair.partition("=")
                    fields[key] = value
                given = fields.get("t", "")
                return path if secrets.compare_digest(given, outer._token) else ""

            def _answer(
                self, code: int, kind: str, body: bytes, close: bool = False
            ) -> None:
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                if close:
                    self.send_header("Connection", "close")
                    self.close_connection = True
                self.end_headers()
                self.wfile.write(body)

            def _json(
                self, payload: dict[str, Any], code: int = 200, close: bool = False
            ) -> None:
                self._answer(
                    code, "application/json", json.dumps(payload).encode(), close
                )

            def _discard(self, length: int) -> int:
                """Read a refused body away, up to `DRAIN_LIMIT`, and say how much.

                A server that answers and closes while the client is still sending
                has the connection aborted under it, and the client never gets to
                read the answer at all (`docs/pitfalls.md` 10.1). Bounded, because
                reading an arbitrary body to be polite about refusing it is the
                thing the refusal exists to avoid.
                """
                left = min(max(length, 0), DRAIN_LIMIT)
                read = 0
                while left > 0:
                    chunk = self.rfile.read(min(left, 64 * 1024))
                    if not chunk:
                        break
                    read += len(chunk)
                    left -= len(chunk)
                return read

            def _missing(self) -> None:
                self._answer(404, "text/plain; charset=utf-8", b"not here")

            def do_GET(self) -> None:
                path = self._allowed()
                if not path:
                    return self._missing()
                if path == "/layout":
                    return self._json(
                        {
                            "layout": write_layout(outer._held),
                            "capabilities": [
                                {"key": key, "name": name, "description": about}
                                for key, name, about in outer._capabilities
                            ],
                        }
                    )
                held = assets.get(path)
                return self._answer(200, *held) if held else self._missing()

            def do_POST(self) -> None:
                path = self._allowed()
                if not path:
                    return self._missing()
                if path == "/done":
                    outer._done()
                    return self._json({"ok": True})
                if path == "/reset":
                    outer._held = Layout()
                    return self._json({"ok": True})
                if path != "/layout":
                    return self._missing()

                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > MAX_BODY:
                    read = self._discard(length)
                    return self._json(
                        {"problems": ["that is not a layout"]}, 413, close=read < length
                    )
                try:
                    document = json.loads(self.rfile.read(length))
                except ValueError:
                    return self._json({"problems": ["that is not JSON"]}, 400)
                return self._json({"problems": list(outer._take(document))})

        return Handler
