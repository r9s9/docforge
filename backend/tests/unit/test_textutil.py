"""Unit tests for the shared text-signal helpers."""

from __future__ import annotations

from docforge.common.textutil import (
    common_skeleton,
    detect_date,
    looks_like_person,
    slugify_field,
    value_kind,
)


def test_detect_date():
    assert detect_date("2026-06-01")
    assert detect_date("Report Date: 2026-06-01")
    assert detect_date("June 1, 2026")
    assert not detect_date("hello world")


def test_value_kind():
    assert value_kind("2026-06-01") == "date"
    assert value_kind("$2,300.00") == "number"
    assert value_kind("42") == "number"
    assert value_kind("Jane Smith") == "person"
    assert value_kind("some free text here") == "text"


def test_looks_like_person():
    assert looks_like_person("Jane Smith")
    assert looks_like_person("John D. Doe")
    assert not looks_like_person("INVOICE")
    assert not looks_like_person("the quick brown fox")


def test_slugify_field():
    assert slugify_field("Project Name:") == "project_name"
    assert slugify_field("Total (USD)") == "total_usd"
    assert slugify_field("Report Date: 2026-06-01") == "report_date"
    assert slugify_field("") == "field"


def test_common_skeleton_splits_prefix():
    prefix, suffix, middles = common_skeleton(
        ["Date: 2026-06-01", "Date: 2025-12-31"]
    )
    assert prefix == "Date: "
    assert suffix == ""
    assert set(middles) == {"2026-06-01", "2025-12-31"}


def test_common_skeleton_no_shared():
    prefix, suffix, middles = common_skeleton(["alpha", "beta"])
    assert prefix is None and suffix is None


def test_common_skeleton_identical_returns_none():
    # identical samples -> no *variable* middle, so not a partial change
    prefix, suffix, middles = common_skeleton(["same", "same"])
    assert prefix is None
