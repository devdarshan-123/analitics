from __future__ import annotations

from urllib.parse import urlsplit


def normalize_path(url_or_path: str | None) -> str:
    """Reduce a URL or path to a comparable page path.

    Strips scheme + domain, query string, fragment and trailing slash.
    "https://example.com/blog/?utm=x#top" -> "/blog", "" -> "/".
    """
    if not url_or_path:
        return "/"
    raw = url_or_path.strip()
    if "://" in raw or raw.startswith("//"):
        path = urlsplit(raw if "://" in raw else "http:" + raw).path
    else:
        path = raw.split("#", 1)[0].split("?", 1)[0]
    if not path.startswith("/"):
        path = "/" + path
    while "//" in path:
        path = path.replace("//", "/")
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    return path
