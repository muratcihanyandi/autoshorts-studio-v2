"""Source output orientation helpers (Task 2, revised 2026-10-24).

A source's ``output_orientation`` decides what the pipeline produces:

- ``auto``      — DEFAULT engine behavior: one trimmed horizontal full cut
                  plus vertical shorts extracted from the same video.
                  The ``reaction_source`` flag is now only a label; it no
                  longer gates full-cut production (user request
                  2026-10-24: "motor hem yatay hem dikey video üretmeli").
- ``vertical``  — vertical shorts only. The horizontal source video is
                  downloaded and processed, the shorts are extracted,
                  then the horizontal file is deleted from disk; only
                  the vertical clips stay in the ready stock.
- ``horizontal``— explicit horizontal output. Identical to ``auto`` today
                  (full cut + shorts); kept so existing source settings
                  keep their meaning without a migration.

Every call site that gates full-cut production must go through
:func:`produces_full_cut` (Python) or :func:`full_cut_sources_condition`
(SQL) so the explicit vertical-only choice always wins.
"""
from __future__ import annotations

from app.models import SourceChannel


def produces_full_cut(source: SourceChannel) -> bool:
    """Does this source render a trimmed horizontal full cut?"""
    return (source.output_orientation or "auto") != "vertical"


def full_cut_sources_condition():
    """SQL criterion matching sources that render a horizontal full cut."""
    return SourceChannel.output_orientation != "vertical"


def vertical_only_condition():
    """SQL criterion matching vertical-only sources (horizontal file
    is deleted after the shorts extraction completes)."""
    return SourceChannel.output_orientation == "vertical"
