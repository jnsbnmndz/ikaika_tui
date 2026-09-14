"""Published releases, read over HTTP from a GitHub-shaped API."""

import asyncio
import fnmatch
import json
import urllib.error
import urllib.parse
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

ALLOWED_SCHEMES = ("http", "https")
"""What a release URL may be, checked before it is opened."""


def require_http(url: str) -> None:
    """Refuse anything `urlopen` would accept that is not a web request.

    `api_base` is guarded by `UpdateSource.problem`, but an asset URL is read out
    of the feed's own response - so the one URL nothing here chose is also the one
    whose file is handed to Windows to execute. `file:` and `ftp:` are schemes
    `urlopen` supports and this has no use for.
    """
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise urllib.error.URLError(f"'{scheme or url}' is not an http or https URL")


TIMEOUT_SECONDS = 15
"""Long enough for a slow connection, short enough that a hung request does not."""

MAX_BYTES = 4 * 1024 * 1024
"""A releases listing is tens of kilobytes. Capped so a wrong `api_base` pointed."""

class HttpReleaseFeed(ReleaseFeedPort):
    def __init__(self, timeout: int = TIMEOUT_SECONDS) -> None:
        self._timeout = timeout

    async def releases(self, source: UpdateSource) -> tuple[Release, ...]:
        problem = source.problem
        if problem:
            raise ReleaseFeedError(problem)
        return await asyncio.to_thread(self._fetch, source)

    def _fetch(self, source: UpdateSource) -> tuple[Release, ...]:
        require_http(source.releases_url)
        request = urllib.request.Request(  # noqa: S310 - require_http above
            source.releases_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/vnd.github+json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 - require_http above
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
            asset_url=str(chosen.get("browser_download_url", "")),
            asset_size=int(chosen.get("size", 0) or 0),
        )


DOWNLOAD_CHUNK = 64 * 1024
"""Read and written a chunk at a time."""

DOWNLOAD_TIMEOUT_SECONDS = 60
"""Per read, not for the whole transfer. A slow connection is allowed to be slow; a."""

PARTIAL_SUFFIX = ".part"
"""What an unfinished download is called."""

class HttpAssetDownload(AssetDownloadPort):
    """`AssetDownloadPort` over `urllib`, in a thread, in chunks."""

    def __init__(self, timeout: int = DOWNLOAD_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout

    async def fetch(self, url: str, target: Path) -> int:
        return await asyncio.to_thread(self._pull, url, target)

    def _pull(self, url: str, target: Path) -> int:
        require_http(url)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 - require_http above
        staging = target.with_suffix(target.suffix + PARTIAL_SUFFIX)
        total = 0
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 - require_http above
            with staging.open("wb") as handle:
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK)
                    if not chunk:
                        break
                    handle.write(chunk)
                    total += len(chunk)
        staging.replace(target)
        return total
