"""The builder's page, as program text.

Here rather than as files under a package directory for the same reason
`handover.py`'s script is here: it ships with the code instead of as something the
frozen build has to be told to carry, and there is then no filesystem for a request
to walk. `builder.py` serves these three constants and nothing else.

The page edits the settings document - the same one App Setup exports and imports -
so nothing in this file decides what a setting is. `docs/decisions/0007`.
"""

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Builder</title>
<link rel="stylesheet" href="builder.css?t=TOKEN">
</head>
<body>
<header class="bar">
  <div class="mark"></div>
  <div>
    <h1>Builder</h1>
    <p class="sub" id="where">Everything the toolbox keeps in its settings file.</p>
  </div>
  <div class="grow"></div>
  <span class="said" id="said"></span>
  <button class="ghost" id="revert" type="button">Revert</button>
  <button class="go" id="save" type="button">Save and close</button>
</header>

<nav class="tabs" id="tabs"></nav>

<main>
  <div class="column" id="sections">
    <section class="pane" data-tab="design">
      <h2>Themes</h2>
      <p class="hint">Add as many as you like and switch between them. The one that is
         on is the one the interface draws itself in.</p>
      <ul class="rows" id="themes"></ul>
      <div class="addRow">
        <input id="themeName" type="text" placeholder="new theme name" maxlength="32">
        <button id="themeAdd" type="button">Add theme</button>
      </div>

      <h2>Colours of <span id="themeIs"></span></h2>
      <p class="hint">Every one is a theme token the interface draws from.</p>
      <div class="swatches" id="swatches"></div>
    </section>

    <section class="pane" data-tab="menu">
      <h2>Menu</h2>
      <p class="hint">Drag to reorder — the numbers follow the order you leave them in.
         Untick to leave one off; you cannot leave them all off, and one left off is
         still reachable with <code>--start</code>.</p>
      <ul id="cards" class="rows"></ul>
      <label class="slider"><span>Cards per row</span>
        <input id="across" type="range" min="1" max="6" step="1">
        <output id="acrossOut"></output>
      </label>
    </section>

    <section class="pane" data-tab="window">
      <h2>Window</h2>
      <p class="hint">Pixels. The interface opens at the first pair and is held to the
         second, and takes both up the next time it starts.</p>
      <div class="pairs" id="sizes"></div>
    </section>

    <section class="pane" data-tab="workspace">
      <h2>Workspace</h2>
      <p class="hint">Where new projects go, what their identifiers are built on, and
         where cloned script repositories are kept.</p>
      <div class="pairs" id="scaffold"></div>
    </section>

    <section class="pane" data-tab="packs">
      <h2>Template packs</h2>
      <p class="hint">Where each stack clones its project template from, and which ref
         of it. A pack with no entry here uses whatever it ships with.</p>
      <div class="table" id="templates"></div>
      <div class="addRow">
        <input id="templateKey" type="text" placeholder="stack key, e.g. react_native">
        <button id="templateAdd" type="button">Add pack</button>
      </div>

      <h2>Script repositories</h2>
      <p class="hint">Where each stack's build scripts are cloned from. Watch asks the
         remote whether the copy in the store has fallen behind.</p>
      <div class="table" id="scripts"></div>
      <div class="addRow">
        <input id="scriptKey" type="text" placeholder="stack key">
        <button id="scriptAdd" type="button">Add repository</button>
      </div>
    </section>

    <section class="pane" data-tab="commands">
      <h2>This project's commands</h2>
      <p class="hint" id="manifestIs"></p>
      <div id="commands"></div>
      <div class="addRow">
        <input id="commandSection" type="text" placeholder="group, e.g. build">
        <input id="commandKey" type="text" placeholder="name (blank = the group is the command)">
        <button id="commandAdd" type="button">Add command</button>
      </div>
    </section>

    <section class="pane" data-tab="updates">
      <h2>Updates</h2>
      <p class="hint">Where the toolbox looks for a newer build of itself. An empty
         repository turns update checking off.</p>
      <div class="pairs" id="updates"></div>
    </section>

    <section class="pane" data-tab="experimental">
      <h2>Experimental</h2>
      <p class="hint">Off by default, and each needs the command to ask for it as well.</p>
      <ul class="rows" id="flags"></ul>
    </section>
  </div>

  <div class="column preview">
    <section class="pane sticky">
      <h2>Preview</h2>
      <div class="frame" id="frame">
        <div class="frameHead">
          <div class="logo">&#9650;</div>
          <div>
            <div class="app">DTI</div>
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
      <p class="pvNote" id="pvNote"></p>
      <h2>Not taken</h2>
      <ul class="problems" id="problems"></ul>
    </section>
  </div>
</main>
<script src="builder.js?t=TOKEN"></script>
</body>
</html>
"""

STYLE = """
:root { color-scheme: dark; --edge: #1d2a38; --dim: #8ba0b6; --gold: #e3a857; }
* { box-sizing: border-box; }
body { margin: 0; font: 14px/1.5 ui-sans-serif, system-ui, sans-serif;
       background: #0b1016; color: #e6edf5; }
.bar { display: flex; align-items: center; gap: 14px; padding: 13px 22px;
       border-bottom: 1px solid var(--edge); background: #0b1016;
       position: sticky; top: 0; z-index: 3; }
.bar h1 { font-size: 16px; margin: 0; }
.sub, .hint { color: var(--dim); font-size: 12px; margin: 2px 0 0; }
.hint { margin: 0 0 12px; }
.hint code { background: #121c26; border-radius: 4px; padding: 1px 4px; }
.mark { width: 22px; height: 22px; border-radius: 5px; background: var(--gold); }
.grow { flex: 1; }
.said { color: var(--dim); font-size: 12px; }
button { font: inherit; border-radius: 7px; padding: 6px 13px; cursor: pointer;
         border: 1px solid #2a3b4e; background: #121c26; color: #e6edf5; }
button.go { background: var(--gold); border-color: var(--gold); color: #10202f; font-weight: 600; }
button.tiny { padding: 3px 8px; font-size: 12px; }
button.risk:hover { border-color: #d9534f; color: #ff9a96; }
button:hover { border-color: var(--gold); }
button:disabled { opacity: .45; cursor: default; }
.tabs { display: flex; gap: 6px; padding: 10px 22px; border-bottom: 1px solid var(--edge);
        position: sticky; top: 61px; background: #0b1016; z-index: 2; overflow-x: auto; }
.tabs button { border: none; background: none; color: var(--dim); padding: 5px 11px; border-radius: 7px; }
.tabs button.on { background: #121c26; color: #e6edf5; }
main { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 420px);
       gap: 18px; padding: 18px 22px 60px; align-items: start; }
@media (max-width: 1000px) { main { grid-template-columns: minmax(0, 1fr); } }
.column { display: grid; gap: 18px; min-width: 0; }
.pane { background: #0f1720; border: 1px solid var(--edge); border-radius: 12px; padding: 18px; }
.pane.hide { display: none; }
.sticky { position: sticky; top: 118px; }
.pane h2 { font-size: 12px; letter-spacing: .09em; text-transform: uppercase;
           color: var(--dim); margin: 22px 0 6px; }
.pane h2:first-child { margin-top: 0; }
.rows { list-style: none; margin: 0 0 14px; padding: 0; display: grid; gap: 8px; }
.rows li { display: flex; align-items: center; gap: 10px; padding: 9px 12px;
           background: #121c26; border: 1px solid #22303f; border-radius: 9px; }
.rows li.grab { cursor: grab; }
.rows li.drag { opacity: .35; }
.rows li.over { border-color: var(--gold); }
.rows li.off .who { opacity: .4; text-decoration: line-through; }
.rows li.on { border-color: var(--gold); }
.handle { color: #5b7188; letter-spacing: 2px; }
.who { flex: 1; min-width: 0; }
.who b { display: block; font-weight: 600; }
.who span { color: var(--dim); font-size: 12px; display: block;
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.slider { display: flex; align-items: center; gap: 12px; }
.slider span { width: 110px; color: var(--dim); font-size: 12px; }
input[type=range] { flex: 1; accent-color: var(--gold); }
.pairs { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.pairs.one { grid-template-columns: 1fr; }
.pairs label { display: grid; gap: 4px; color: var(--dim); font-size: 12px; min-width: 0; }
input[type=text], input[type=number], select {
  font: inherit; padding: 7px 9px; border-radius: 7px; min-width: 0;
  border: 1px solid #2a3b4e; background: #0b1016; color: #e6edf5; }
input:focus, select:focus { outline: none; border-color: var(--gold); }
.table { display: grid; gap: 8px; margin-bottom: 12px; }
.line { display: grid; grid-template-columns: 130px 1fr 130px auto; gap: 8px;
        align-items: center; background: #121c26; border: 1px solid #22303f;
        border-radius: 9px; padding: 9px 11px; }
.line.watched { grid-template-columns: 130px 1fr 110px auto auto; }
.line b { font-weight: 600; overflow: hidden; text-overflow: ellipsis; }
.line .watch { display: flex; align-items: center; gap: 5px; color: var(--dim); font-size: 12px; }
.addRow { display: flex; gap: 8px; margin-bottom: 4px; }
.addRow input { flex: 1; }
.empty { color: #5b7188; font-size: 12px; padding: 4px 0 10px; }
.swatches { display: grid; grid-template-columns: repeat(auto-fill, minmax(155px, 1fr)); gap: 10px; }
.swatch { display: flex; align-items: center; gap: 9px; background: #121c26;
          border: 1px solid #22303f; border-radius: 9px; padding: 7px 10px; }
.swatch input { width: 30px; height: 30px; padding: 0; border: none; background: none; cursor: pointer; }
.swatch span { font-size: 12px; color: var(--dim); }
.cmd { background: #121c26; border: 1px solid #22303f; border-radius: 9px;
       padding: 11px 12px; margin-bottom: 10px; display: grid; gap: 8px; }
.cmd .names { display: grid; grid-template-columns: 1fr 1fr auto; gap: 8px; align-items: center; }
.cmd .lines { display: grid; gap: 6px; }
.cmd .line2 { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
.cmd .flags { display: flex; gap: 16px; align-items: center; color: var(--dim); font-size: 12px; }
.cmd .flags label { display: flex; gap: 5px; align-items: center; }
.cmd .kept { color: #5b7188; font-size: 11px; }
.cmd textarea { font: inherit; padding: 7px 9px; border-radius: 7px; resize: vertical;
                border: 1px solid #2a3b4e; background: #0b1016; color: #e6edf5; min-height: 34px; }
.problems { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.problems li { font-size: 12px; color: #e8a49f; background: #1b1113;
               border: 1px solid #3a2226; border-radius: 7px; padding: 6px 9px; }
.problems li.none { color: #5b7188; background: none; border-color: transparent; padding: 0; }
.frame { border: 1px solid; border-radius: 10px; overflow: hidden; font-family: ui-monospace, monospace; }
.frameHead { display: flex; align-items: center; gap: 10px; padding: 9px 13px; border-bottom: 1px solid; }
.logo { font-size: 17px; }
.app { font-weight: 700; letter-spacing: .12em; }
.tag, .ver { font-size: 11px; opacity: .75; }
.frameBody { padding: 15px 13px 18px; }
.pvTitle { font-weight: 700; }
.pvSub { font-size: 12px; opacity: .7; margin-bottom: 13px; }
.grid { display: grid; gap: 8px; }
.card { border: 1px solid; border-radius: 7px; padding: 8px 10px; font-size: 12px; min-width: 0; }
.card b { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card i { font-style: normal; opacity: .65; font-size: 11px; overflow: hidden;
          display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.card.first { border-width: 2px; }
.frameFoot { padding: 8px 13px; border-top: 1px solid; font-size: 11px; opacity: .8; }
.pvNote { margin: 9px 2px 0; font-size: 11px; color: var(--dim); }
.pvNote em { font-style: normal; color: #e8a49f; }
.key { font-weight: 700; margin-left: 10px; }
.key:first-child { margin-left: 0; }
"""

SCRIPT = """
const token = new URLSearchParams(location.search).get("t") || "";
const url = (path) => path + "?t=" + encodeURIComponent(token);
const $ = (id) => document.getElementById(id);
const make = (tag, props) => Object.assign(document.createElement(tag), props || {});

const TABS = [
  ["design", "Design"], ["menu", "Menu"], ["window", "Window"],
  ["workspace", "Workspace"], ["packs", "Packs"], ["commands", "Commands"],
  ["updates", "Updates"], ["experimental", "Experimental"],
];
const FLAGS = [
  ["interactive_lists", "Interactive lists", "A command may hand over rows to pick from."],
  ["timed_prompts", "Timed prompts", "One of those lists may count down to an answer."],
  ["browser_view", "Browser view", "A command may open the two-pane browser."],
];
const SIZES = [
  ["start_width", "Opens at (w)"], ["start_height", "Opens at (h)"],
  ["min_width", "No smaller than (w)"], ["min_height", "No smaller than (h)"],
];
const PLACES = [
  ["workspace_root", "Workspace root"], ["bundle_prefix", "Bundle prefix"],
  ["scripts_root", "Scripts root"],
];
const FEED = [
  ["repository", "Repository", "owner/name, not a URL"],
  ["api_base", "API host", "the API root"],
  ["asset_pattern", "Installer pattern", "which asset of a release is the installer"],
];

let doc = null;
let known = [];
let channels = [];
let commands = [];
let manifest = "";
let tab = "design";

const say = (text) => { $("said").textContent = text; };

async function load() {
  const body = await (await fetch(url("/document"))).json();
  doc = body.document;
  known = body.capabilities;
  channels = body.channels;
  commands = body.commands || [];
  manifest = body.manifest || "";
  $("where").textContent = body.where;
  showProblems([]);
  render();
}

async function push() {
  const answer = await fetch(url("/document"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(doc),
  });
  const body = await answer.json();
  showProblems(body.problems || []);
  if (body.problems && body.problems.length) {
    doc = body.document;
    render();
    say("Some of that was not taken.");
  } else {
    say("Held.");
  }
}

function showProblems(problems) {
  const list = $("problems");
  list.textContent = "";
  if (!problems.length) {
    list.append(make("li", { className: "none", textContent: "Nothing so far." }));
    return;
  }
  problems.forEach((one) => list.append(make("li", { textContent: one })));
}

function render() {
  drawTabs();
  drawThemes();
  drawSwatches();
  drawCards();
  drawPairs($("sizes"), SIZES, doc.layout.window, (key, field) => {
    doc.layout.window[key] = parseInt(field.value, 10) || doc.layout.window[key];
    drawPreview();
  }, "number");
  drawPairs($("scaffold"), PLACES, doc.scaffold, (key, field) => {
    doc.scaffold[key] = field.value;
  });
  drawSources("templates", $("templates"), false);
  drawSources("scripts", $("scripts"), true);
  drawUpdates();
  drawFlags();
  drawCommands();
  $("across").value = doc.layout.menu.cards_per_row;
  $("acrossOut").textContent = doc.layout.menu.cards_per_row;
  drawPreview();
}

function drawTabs() {
  const bar = $("tabs");
  bar.textContent = "";
  TABS.forEach(([key, label]) => {
    const button = make("button", { type: "button", textContent: label });
    if (key === tab) button.classList.add("on");
    button.addEventListener("click", () => { tab = key; drawTabs(); showTab(); });
    bar.append(button);
  });
  showTab();
}

function showTab() {
  document.querySelectorAll("[data-tab]").forEach((pane) => {
    pane.classList.toggle("hide", pane.dataset.tab !== tab);
  });
}

/* ---- themes: add, rename, duplicate, delete, activate ---- */

function themeNames() { return Object.keys(doc.layout.themes); }

function drawThemes() {
  const list = $("themes");
  list.textContent = "";
  const names = themeNames();
  names.forEach((name) => {
    const row = make("li");
    if (name === doc.layout.theme) row.classList.add("on");

    const pick = make("input", { type: "radio", name: "theme", checked: name === doc.layout.theme });
    pick.addEventListener("change", () => { doc.layout.theme = name; render(); push(); });

    const field = make("input", { type: "text", value: name, maxLength: 32 });
    field.style.flex = "1";
    field.addEventListener("change", () => rename(name, field.value.trim()));

    const copy = make("button", { type: "button", className: "tiny", textContent: "Duplicate" });
    copy.addEventListener("click", () => duplicate(name));

    const drop = make("button", { type: "button", className: "tiny risk", textContent: "Delete" });
    drop.disabled = names.length < 2;
    drop.addEventListener("click", () => remove(name));

    row.append(pick, field, copy, drop);
    list.append(row);
  });
  $("themeIs").textContent = doc.layout.theme;
}

function freeName(wanted) {
  let name = wanted;
  let n = 2;
  while (doc.layout.themes[name]) { name = wanted + "-" + n; n += 1; }
  return name;
}

function addTheme() {
  const asked = $("themeName").value.trim();
  if (!asked) { say("Give it a name first."); return; }
  const name = freeName(asked);
  doc.layout.themes[name] = { ...doc.layout.themes[doc.layout.theme] };
  doc.layout.theme = name;
  $("themeName").value = "";
  render();
  push();
}

function duplicate(name) {
  const copy = freeName(name + "-copy");
  doc.layout.themes[copy] = { ...doc.layout.themes[name] };
  doc.layout.theme = copy;
  render();
  push();
}

function rename(from, to) {
  if (!to || to === from) { render(); return; }
  if (doc.layout.themes[to]) { say("There is already a theme called that."); render(); return; }
  const kept = {};
  Object.keys(doc.layout.themes).forEach((name) => {
    kept[name === from ? to : name] = doc.layout.themes[name];
  });
  doc.layout.themes = kept;
  if (doc.layout.theme === from) doc.layout.theme = to;
  render();
  push();
}

function remove(name) {
  if (themeNames().length < 2) { say("There has to be one theme."); return; }
  delete doc.layout.themes[name];
  if (doc.layout.theme === name) doc.layout.theme = themeNames()[0];
  render();
  push();
}

function drawSwatches() {
  const holder = $("swatches");
  holder.textContent = "";
  const palette = doc.layout.themes[doc.layout.theme] || {};
  Object.keys(palette).forEach((key) => {
    const cell = make("div", { className: "swatch" });
    const pick = make("input", { type: "color", value: palette[key] });
    pick.addEventListener("input", () => { palette[key] = pick.value; drawPreview(); });
    pick.addEventListener("change", push);
    cell.append(pick, make("span", { textContent: key }));
    holder.append(cell);
  });
}

/* ---- the menu ---- */

function ordered() {
  const keys = known.map((one) => one.key);
  const wanted = (doc.layout.menu.order || []).filter((k) => keys.includes(k));
  keys.forEach((k) => { if (!wanted.includes(k)) wanted.push(k); });
  return wanted.map((k) => known.find((one) => one.key === k));
}

function shown() {
  const off = doc.layout.menu.hidden || [];
  const on = ordered().filter((one) => !off.includes(one.key));
  return on.length ? on : ordered();
}

function drawCards() {
  const list = $("cards");
  list.textContent = "";
  ordered().forEach((one) => {
    const off = (doc.layout.menu.hidden || []).includes(one.key);
    const row = make("li", { className: "grab" + (off ? " off" : "") });
    row.draggable = true;
    row.dataset.key = one.key;

    const box = make("input", { type: "checkbox", checked: !off });
    box.addEventListener("change", () => toggleCard(one.key));

    const who = make("div", { className: "who" });
    who.append(make("b", { textContent: one.name }),
               make("span", { textContent: one.description }));

    row.append(make("span", { className: "handle", textContent: "::" }), box, who);
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
    doc.layout.menu.order = [...$("cards").children].map((n) => n.dataset.key);
    drawPreview();
    push();
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

function toggleCard(key) {
  const off = new Set(doc.layout.menu.hidden || []);
  if (off.has(key)) { off.delete(key); } else { off.add(key); }
  if (off.size >= known.length) { say("At least one card has to stay."); drawCards(); return; }
  doc.layout.menu.hidden = [...off];
  drawCards();
  drawPreview();
  push();
}

/* ---- plain fields ---- */

function drawPairs(holder, fields, held, take, kind) {
  holder.textContent = "";
  fields.forEach(([key, label]) => {
    const wrap = make("label");
    const field = make("input", { type: kind || "text", value: held[key] });
    if (kind === "number") { field.min = 320; field.max = 10000; field.step = 10; }
    field.addEventListener("change", () => { take(key, field); push(); });
    wrap.append(make("span", { textContent: label }), field);
    holder.append(wrap);
  });
}

function drawUpdates() {
  const holder = $("updates");
  holder.textContent = "";
  FEED.forEach(([key, label, about]) => {
    const wrap = make("label");
    const field = make("input", { type: "text", value: doc.updates[key], title: about });
    field.addEventListener("change", () => { doc.updates[key] = field.value.trim(); push(); });
    wrap.append(make("span", { textContent: label }), field);
    holder.append(wrap);
  });
  const wrap = make("label");
  const pick = make("select");
  channels.forEach((one) => {
    const option = make("option", { value: one.value, textContent: one.label });
    if (one.value === doc.updates.channel) option.selected = true;
    pick.append(option);
  });
  pick.addEventListener("change", () => { doc.updates.channel = pick.value; push(); });
  wrap.append(make("span", { textContent: "Channel" }), pick);
  holder.append(wrap);
}

function drawFlags() {
  const list = $("flags");
  list.textContent = "";
  FLAGS.forEach(([key, label, about]) => {
    const row = make("li");
    const box = make("input", { type: "checkbox", checked: doc.experimental[key] === true });
    box.addEventListener("change", () => { doc.experimental[key] = box.checked; push(); });
    const who = make("div", { className: "who" });
    who.append(make("b", { textContent: label }), make("span", { textContent: about }));
    row.append(box, who);
    list.append(row);
  });
}

/* ---- sources: add, update, delete ---- */

function drawSources(section, holder, watched) {
  holder.textContent = "";
  const held = doc[section] || {};
  const keys = Object.keys(held).sort();
  if (!keys.length) {
    holder.append(make("div", { className: "empty", textContent: "None yet." }));
    return;
  }
  keys.forEach((key) => {
    const line = make("div", { className: "line" + (watched ? " watched" : "") });
    line.append(make("b", { textContent: key }));

    const address = make("input", { type: "text", value: held[key].url || "", placeholder: "clone URL" });
    address.addEventListener("change", () => { held[key].url = address.value.trim(); push(); });

    const ref = make("input", { type: "text", value: held[key].ref || "", placeholder: "ref" });
    ref.addEventListener("change", () => { held[key].ref = ref.value.trim(); push(); });

    line.append(address, ref);

    if (watched) {
      const wrap = make("label", { className: "watch" });
      const box = make("input", { type: "checkbox" });
      box.checked = doc.script_checks[key] !== false;
      box.addEventListener("change", () => { doc.script_checks[key] = box.checked; push(); });
      wrap.append(box, make("span", { textContent: "Watch" }));
      line.append(wrap);
    }

    const drop = make("button", { type: "button", className: "tiny risk", textContent: "Delete" });
    drop.addEventListener("click", () => {
      delete held[key];
      if (watched) delete doc.script_checks[key];
      render();
      push();
    });
    line.append(drop);
    holder.append(line);
  });
}

function addSource(section, field, watched) {
  const key = field.value.trim();
  if (!key) { say("Give it a stack key first."); return; }
  if (doc[section][key]) { say("There is already one for that stack."); return; }
  doc[section][key] = { url: "", ref: "" };
  if (watched) doc.script_checks[key] = true;
  field.value = "";
  render();
  say("Give it a clone URL — one with no URL is not written down.");
}

/* ---- the project's own commands ---- */

async function pushCommands() {
  const answer = await fetch(url("/commands"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ commands: commands }),
  });
  const body = await answer.json();
  commands = body.commands || [];
  say("Held. Anything it will not take is reported when you save.");
}

function drawCommands() {
  const holder = $("commands");
  holder.textContent = "";
  const where = $("manifestIs");
  if (!manifest) {
    where.textContent = "This project declares no commands, and the builder will not"
      + " start one for it — what makes a directory one of these projects is a"
      + " scaffold, not this page.";
    $("commandAdd").disabled = true;
    return;
  }
  where.textContent = "Read from " + manifest + ". Only what is shown here is written;"
    + " everything else on a command is put back untouched.";
  $("commandAdd").disabled = false;

  if (!commands.length) {
    holder.append(make("div", { className: "empty", textContent: "None yet." }));
  }
  commands.forEach((one, index) => holder.append(drawCommand(one, index)));
}

function drawCommand(one, index) {
  const card = make("div", { className: "cmd" });

  const names = make("div", { className: "names" });
  const section = make("input", { type: "text", value: one.section, placeholder: "group" });
  section.addEventListener("change", () => {
    one.section = section.value.trim();
    pushCommands();
  });
  const key = make("input", { type: "text", value: one.key, placeholder: "name (optional)" });
  key.addEventListener("change", () => {
    one.key = key.value.trim();
    pushCommands();
  });
  const drop = make("button", { type: "button", className: "tiny risk", textContent: "Delete" });
  drop.addEventListener("click", () => {
    commands.splice(index, 1);
    drawCommands();
    pushCommands();
  });
  names.append(section, key, drop);

  const about = make("input", {
    type: "text", value: one.description, placeholder: "what it is for",
  });
  about.addEventListener("change", () => {
    one.description = about.value;
    pushCommands();
  });

  const lines = make("div", { className: "lines" });
  const held = one.commands.length ? one.commands : [""];
  held.forEach((line, at) => {
    const row = make("div", { className: "line2" });
    const field = make("textarea", { rows: 1, placeholder: "the command to run" });
    field.value = line;
    field.addEventListener("change", () => {
      const next = one.commands.length ? one.commands.slice() : [""];
      next[at] = field.value.trim();
      one.commands = next;
      pushCommands();
    });
    const less = make("button", { type: "button", className: "tiny risk", textContent: "−" });
    less.addEventListener("click", () => {
      one.commands = held.filter((_, n) => n !== at);
      drawCommands();
      pushCommands();
    });
    row.append(field, less);
    lines.append(row);
  });

  const more = make("button", { type: "button", className: "tiny", textContent: "Add a line" });
  more.addEventListener("click", () => {
    one.commands = held.concat([""]);
    drawCommands();
  });

  const flags = make("div", { className: "flags" });
  const FIELDS = [["interactive", "Speaks the list protocol"], ["view", "Opens the browser view"]];
  FIELDS.forEach((pair) => {
    const field = pair[0];
    const wrap = make("label");
    const box = make("input", { type: "checkbox" });
    box.checked = field === "view" ? one.view === "browser" : one.interactive === true;
    box.addEventListener("change", () => {
      if (field === "view") {
        one.view = box.checked ? "browser" : "";
      } else {
        one.interactive = box.checked;
      }
      pushCommands();
    });
    wrap.append(box, make("span", { textContent: pair[1] }));
    flags.append(wrap);
  });
  if (one.kept && one.kept.length) {
    flags.append(make("span", {
      className: "kept", textContent: "kept as it is: " + one.kept.join(", "),
    }));
  }

  card.append(names, about, lines, more, flags);
  return card;
}

function addCommand() {
  const section = $("commandSection").value.trim();
  if (!section) {
    say("Give it a group first.");
    return;
  }
  commands.push({
    section: section,
    key: $("commandKey").value.trim(),
    description: "",
    commands: [""],
    interactive: false,
    view: "",
    kept: [],
    was: "",
  });
  $("commandSection").value = "";
  $("commandKey").value = "";
  drawCommands();
  pushCommands();
}

/* ---- the preview ---- */

function painting() {
  const held = doc.layout.themes || {};
  return held[doc.layout.theme] || held[Object.keys(held)[0]] || {};
}

function drawPreview() {
  const paint = painting();
  const frame = $("frame");
  frame.style.background = paint.background;
  frame.style.color = paint.foreground;
  frame.style.borderColor = paint.primary;
  frame.querySelector(".frameHead").style.borderColor = paint.primary;
  frame.querySelector(".frameHead").style.background = paint.surface;
  frame.querySelector(".frameFoot").style.borderColor = paint.primary;
  frame.querySelector(".logo").style.color = paint.accent;

  const grid = $("pvGrid");
  grid.style.gridTemplateColumns =
    "repeat(" + doc.layout.menu.cards_per_row + ", minmax(0, 1fr))";
  grid.textContent = "";
  shown().forEach((one, index) => {
    const card = make("div", { className: "card" + (index === 0 ? " first" : "") });
    card.style.background = paint.panel;
    card.style.borderColor = index === 0 ? paint.accent : paint.secondary;
    card.append(
      make("b", { textContent: "[" + String(index + 1).padStart(2, "0") + "] " + one.name }),
      make("i", { textContent: one.description }),
    );
    grid.append(card);
  });

  shapeFrame();
  describePreview();
}

function shapeFrame() {
  const frame = $("frame");
  const held = doc.layout.window;
  const wide = held.start_width || 1;
  const tall = held.start_height || 1;
  const across = frame.getBoundingClientRect().width;
  frame.style.minHeight = across ? Math.round((across * tall) / wide) + "px" : "";
}

function describePreview() {
  const note = $("pvNote");
  const held = doc.layout.window;
  note.textContent = doc.layout.theme
    + " - opens " + held.start_width + "x" + held.start_height
    + ", never under " + held.min_width + "x" + held.min_height
    + " - " + doc.layout.menu.cards_per_row + " across"
    + " - " + shown().length + " of " + known.length + " cards";
  if (held.start_width < held.min_width || held.start_height < held.min_height) {
    note.append(make("em", { textContent: " - it opens under its own floor" }));
  }
}

/* ---- wiring ---- */

$("across").addEventListener("input", (event) => {
  doc.layout.menu.cards_per_row = parseInt(event.target.value, 10);
  $("acrossOut").textContent = doc.layout.menu.cards_per_row;
  drawPreview();
});
$("across").addEventListener("change", push);
window.addEventListener("resize", shapeFrame);
$("themeAdd").addEventListener("click", addTheme);
$("commandAdd").addEventListener("click", addCommand);
$("templateAdd").addEventListener("click", () => addSource("templates", $("templateKey"), false));
$("scriptAdd").addEventListener("click", () => addSource("scripts", $("scriptKey"), true));

$("revert").addEventListener("click", async () => {
  await fetch(url("/revert"), { method: "POST" });
  await load();
  say("Back to what it was when this opened.");
});

$("save").addEventListener("click", async () => {
  await push();
  await pushCommands();
  await fetch(url("/done"), { method: "POST" });
  say("Saved. You can close this tab.");
  $("save").disabled = true;
  $("revert").disabled = true;
});

load();
"""
