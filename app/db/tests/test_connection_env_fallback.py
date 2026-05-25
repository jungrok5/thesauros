"""Regression guard for SUPABASE_URL → NEXT_PUBLIC_SUPABASE_URL fallback.

Origin: 2026-05-25 — Vercel `/api/us-analysis` raised `KeyError:
'SUPABASE_URL'` because the prod env only had `NEXT_PUBLIC_SUPABASE_URL`
registered (web-next reads it for the browser client). Python code was
hard-coded to require the prefix-free name; introducing fallback makes
the Python serverless functions work without forcing users to duplicate
the same value under two env names.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.db.connection import _read_supabase_url


def test_prefers_prefix_free_when_both_present():
    """If both SUPABASE_URL and NEXT_PUBLIC_SUPABASE_URL exist, the
    prefix-free name wins — it's the historical Python convention."""
    with patch.dict(
        os.environ,
        {
            "SUPABASE_URL": "https://direct.supabase.co",
            "NEXT_PUBLIC_SUPABASE_URL": "https://nextpublic.supabase.co",
        },
        clear=True,
    ):
        assert _read_supabase_url() == "https://direct.supabase.co"


def test_falls_back_to_next_public_when_only_that_exists():
    """The reason this fallback exists at all."""
    with patch.dict(
        os.environ,
        {"NEXT_PUBLIC_SUPABASE_URL": "https://nextpublic.supabase.co"},
        clear=True,
    ):
        assert _read_supabase_url() == "https://nextpublic.supabase.co"


def test_raises_with_helpful_message_when_both_missing():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(KeyError, match="SUPABASE_URL"):
            _read_supabase_url()
