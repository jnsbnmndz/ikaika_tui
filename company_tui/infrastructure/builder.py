"""The one-off server that hands the builder's page to a browser.

A design-time tool, so it is a browser rather than a screen: dragging a grid into
shape with a mouse is a thing browsers do well and a terminal does badly. Everything
about the server follows from it being open for as long as somebody is arranging
things and not one second longer.

- **`127.0.0.1` on an ephemeral port**, so nothing on the network can reach it.
- **A single-use token on every request**, because localhost is not a boundary: any
  program on this machine can reach a loopback port, and any page in the browser can
  POST to one. Without the token every path answers 404, which is also what a wrong
  token gets - a 403 confirms the path.
- **Assets from a dict, never from the filesystem**, so there is no path to traverse.
- **A refused body is read away before the refusal is sent**, or answering while the
  client is still writing aborts the connection under it and the refusal never
  arrives (`docs/pitfalls.md` 10.1).
- **Nothing is written here.** What the page edits is the settings document - the
  same one App Setup exports and imports, through the same pair that reads and
  writes it - and saving it is the capability's, through `ConfigPort` like every
  other setting. The browser is a second *editor*, never a second definition of what
  a setting is.

See `docs/decisions/0007`.
"""

import asyncio
import json
import secrets
import threading
from collections.abc import Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from company_tui.domain.config import Settings
from company_tui.domain.settings_document import read_document, write_document
from company_tui.domain.updates import CHANNEL_LABELS, CHANNELS
from company_tui.infrastructure.builder_page import PAGE, SCRIPT, STYLE

HOST = "127.0.0.1"
MAX_BODY = 256 * 1024
"""A settings document is a page of them. Anything past this is not one."""

DRAIN_LIMIT = 4 * MAX_BODY
"""How much of a refused body is read away before the connection is dropped instead."""


class BuilderServer:
    """One page, on this machine, for as long as somebody is arranging things."""

    def __init__(
        self,
        settings: Settings,
        capabilities: Sequence[tuple[str, str, str]],
        loop: asyncio.AbstractEventLoop | None = None,
        where: str = "",
    ) -> None:
        self._opened_with = settings
        self._held = settings
        self._capabilities = tuple(capabilities)
        self._where = where
        self._token = secrets.token_urlsafe(32)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._loop = loop
        self.finished = asyncio.Event()
        self.problems: tuple[str, ...] = ()

    @property
    def settings(self) -> Settings:
        """What the page has made of them so far, valid at every moment in between."""
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
        self._held, problems = read_document(document, self._held)
        self.problems = problems
        return problems

    def _offered(self) -> dict[str, Any]:
        return {
            "document": write_document(self._held),
            "capabilities": [
                {"key": key, "name": name, "description": about}
                for key, name, about in self._capabilities
            ],
            "channels": [
                {"value": name, "label": CHANNEL_LABELS.get(name, name)}
                for name in CHANNELS
            ],
            "where": self._where,
        }

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
                if path == "/document":
                    return self._json(outer._offered())
                held = assets.get(path)
                return self._answer(200, *held) if held else self._missing()

            def do_POST(self) -> None:
                """Take an edit, or end the run.

                What goes back is the document as it was actually read, so a page
                showing a value the toolbox would not take corrects itself rather
                than standing there claiming it was kept.
                """
                path = self._allowed()
                if not path:
                    return self._missing()
                if path == "/done":
                    outer._done()
                    return self._json({"ok": True})
                if path == "/revert":
                    outer._held = outer._opened_with
                    outer.problems = ()
                    return self._json({"ok": True})
                if path != "/document":
                    return self._missing()

                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > MAX_BODY:
                    read = self._discard(length)
                    return self._json(
                        {"problems": ["that is not a settings document"]},
                        413,
                        close=read < length,
                    )
                try:
                    document = json.loads(self.rfile.read(length))
                except ValueError:
                    return self._json({"problems": ["that is not JSON"]}, 400)
                problems = outer._take(document)
                return self._json(
                    {
                        "problems": list(problems),
                        "document": write_document(outer._held),
                    }
                )

        return Handler
