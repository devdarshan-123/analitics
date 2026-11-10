from __future__ import annotations

import pytest

from app.services.combined import percentile
from app.utils.paths import normalize_path


@pytest.mark.parametrize("raw,expected", [
    ("https://www.example.com/pricing/?ref=nav", "/pricing"),
    ("https://www.example.com/pricing", "/pricing"),
    ("http://example.com/", "/"),
    ("https://example.com", "/"),
    ("/blog/post-1/", "/blog/post-1"),
    ("/blog/post-1?utm_source=x#comments", "/blog/post-1"),
    ("blog", "/blog"),
    ("//cdn.example.com/a/b/", "/a/b"),
    ("/a//b///", "/a/b"),
    ("", "/"),
    (None, "/"),
    ("/", "/"),
    ("  /Pricing/  ", "/Pricing"),
])
def test_normalize_path(raw, expected):
    assert normalize_path(raw) == expected


def test_percentile():
    assert percentile([], 75) == 0
    assert percentile([5], 75) == 5
    assert percentile(list(range(1, 101)), 75) == 75
