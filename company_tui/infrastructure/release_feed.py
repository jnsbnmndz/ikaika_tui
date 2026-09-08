"""Published releases, read over HTTP from a GitHub-shaped API.

`urllib` from the standard library rather than `requests` or `httpx`. The app has
exactly one dependency - textual - and it is frozen with PyInstaller, so every
addition is another thing to collect into the bundle and another chance of the
frozen build differing from the checkout. One GET returning JSON does not justify
that.


THE USER-AGENT IS NOT OPTIONAL

GitHub rejects an API request with no User-Agent, with a 403 whose body explains
why - but the check that would be looked at first is the repository name, so the
failure reads as "no releases found" for a repository that plainly has some.


EVERY FAILURE BECOMES ONE SENTENCE

A network error, a 404, a rate limit and a body that is not JSON are four
different things a person can act on: check the connection, check the name, wait
or authenticate, and report a bug. They are told apart here, because by the time
this returns there is nothing left to tell them apart with.

Rate limiting is the one worth naming explicitly. Unauthenticated GitHub allows
60 requests an hour per IP, which is generous for a person and immediate for a
machine behind a shared address - and its 403 otherwise reads as "forbidden",
which sounds like a permissions problem nobody can fix.
"""

import asyncio
import fnmatch
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from company_tui.domain.updates import (
    USER_AGENT,
    AssetDownloadPort,
    Release,
    ReleaseFeedError,
    ReleaseFeedPort,
    UpdateSource,
)

TIMEOUT_SECONDS = 15
"""Long enough for a slow connection, short enough that a hung request does not
look like the check having silently stopped. The request runs off the interface
thread either way, so this bounds the wait rather than the responsiveness."""

MAX_BYTES = 4 * 1024 * 1024
"""A releases listing is tens of kilobytes. Capped so a wrong `api_base` pointed
at something that streams cannot exhaust memory - the read is bounded before the
body is parsed, not after."""



class HttpReleaseFeed(ReleaseFeedPort):
    def __init__(self, timeout: int = TIMEOUT_SECONDS) -> None:
        self._timeout = timeout

    async def releases(self, source: UpdateSource) -> tuple[Release, ...]:
        problem = source.problem
        if problem:
            raise ReleaseFeedError(problem)
        # to_thread, because urllib is blocking: called inline it would stop the
        # interface redrawing and stop it answering the key that cancels.
        return await asyncio.to_thread(self._fetch, source)

    def _fetch(self, source: UpdateSource) -> tuple[Release, ...]:
        request = urllib.request.Request(
            source.releases_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/vnd.github+json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read(MAX_BYTES)
        except urllib.error.HTTPError as error:
            raise ReleaseFeedError(self._http_problem(error, source)) from error
        except urllib.error.URLError as error:
            raise ReleaseFeedError(
                f"could not reach {source.api_base} - {error.reason}"
            ) from error
        except (TimeoutError, OSError) as error:
            raise ReleaseFeedError(f"the request failed - {error}") from error

        try:
            document = json.loads(raw.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ReleaseFeedError(
                f"{source.api_base} did not answer with JSON - {error}"
            ) from error

        if not isinstance(document, list):
            # A single object here is what /releases/latest returns, so this is
            # the shape somebody gets from pasting that URL as the api_base.
            raise ReleaseFeedError(
                "expected a list of releases; check that api_base is the API root"
            )
        return tuple(self._release(entry, source) for entry in document if isinstance(entry, dict))

    @staticmethod
    def _http_problem(error: urllib.error.HTTPError, source: UpdateSource) -> str:
        if error.code == 404:
            return (
                f"there is no repository called {source.repository} "
                "(or it is private to this token)"
            )
        if error.code in (403, 429):
            remaining = error.headers.get("X-RateLimit-Remaining") if error.headers else None
            if remaining == "0":
                return (
                    "GitHub is rate limiting this address - unauthenticated requests "
                    "are capped at 60 an hour. Try again later."
                )
            return f"{source.api_base} refused the request ({error.code})"
        return f"{source.api_base} answered {error.code} {error.reason}"

    @staticmethod
    def _release(entry: dict[str, Any], source: UpdateSource) -> Release:
        assets = entry.get("assets")
        assets = assets if isinstance(assets, list) else []
        chosen: dict[str, Any] = {}
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name", ""))
            if fnmatch.fnmatch(name.lower(), source.asset_pattern.lower()):
                chosen = asset
                break

        return Release(
            tag=str(entry.get("tag_name", "")),
            name=str(entry.get("name") or entry.get("tag_name") or ""),
            prerelease=entry.get("prerelease", False) is True,
            notes=str(entry.get("body") or ""),
            page_url=str(entry.get("html_url") or ""),
            asset_name=str(chosen.get("name", "")),
            # browser_download_url, not `url`: the latter is the API's own asset
            # endpoint, which answers with JSON metadata unless asked for an
            # octet-stream - so a download built on it silently saves a JSON
            # document named like an installer.
            asset_url=str(chosen.get("browser_download_url", "")),
            asset_size=int(chosen.get("size", 0) or 0),
        )


DOWNLOAD_CHUNK = 64 * 1024
"""Read and written a chunk at a time.

An installer is tens of megabytes. Read whole into memory it is held twice - once in the
buffer and once on the way to disk - which on the smallest machine this runs on is the
difference between a download and a swap storm.
"""

DOWNLOAD_TIMEOUT_SECONDS = 60
"""Per read, not for the whole transfer. A slow connection is allowed to be slow; a
connection that has stopped answering is not allowed to look like one."""

PARTIAL_SUFFIX = ".part"
"""What an unfinished download is called.

The finished name is only ever a file that finished. A partial file under the real name
is an installer somebody's app will offer to run, and there is no way to tell it from a
whole one by looking - which is why the launch check is allowed to trust a path it read
out of a file written by a previous launch.
"""


class HttpAssetDownload(AssetDownloadPort):
    """`AssetDownloadPort` over `urllib`, in a thread, in chunks."""

    def __init__(self, timeout: int = DOWNLOAD_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout

    async def fetch(self, url: str, target: Path) -> int:
        # to_thread, because urllib is blocking: called inline it would stop the
        # interface redrawing, and this one runs while the user is looking at a menu
        # rather than at a progress bar.
        return await asyncio.to_thread(self._pull, url, target)

    def _pull(self, url: str, target: Path) -> int:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        staging = target.with_suffix(target.suffix + PARTIAL_SUFFIX)
        total = 0
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            with staging.open("wb") as handle:
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK)
                    if not chunk:
                        break
                    handle.write(chunk)
                    total += len(chunk)
        # Moved into place only once every byte is written. `replace` rather than
        # `rename`, so a leftover from an interrupted run is overwritten instead of
        # raising on Windows.
        staging.replace(target)
        return total
