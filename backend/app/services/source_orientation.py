"""Source output orientation helpers (Task 2).

A source's ``output_orientation`` decides what the pipeline produces:

- ``auto``      — legacy behavior: the ``reaction_source`` flag decides
                  whether a trimmed horizontal full cut is rendered
                  (reaction sources also produce vertical shorts).
- ``vertical``  — vertical shorts only. The horizontal source video is
                  downloaded and processed, the shorts are extracted,
                  then the horizontal file is deleted from disk; only
                  the vertical clips stay in the ready stock.
- ``horizontal``— the trimmed horizontal full cut is produced regardless
                  of the reaction flag (plus vertical shorts, exactly
                  like a reaction source).

Every call site that used ``source.reaction_source`` to gate full-cut
production must go through :func:`produces_full_cut` so the explicit
orientation always wins.
"""
from __future__ import annotations

import sqlalchemy as sa

from app.models import SourceChannel


def produces_full_cut(source: SourceChannel) -> bool:
    """Does this source render a trimmed horizontal full cut?"""
    orientation = source.output_orientation or "auto"
    if orientation == "vertical":
        return False
    if orientation == "horizontal":
        return True
    return bool(source.reaction_source)


def full_cut_sources_condition():
    """SQL criterion matching sources that render a horizontal full cut."""
    return sa.or_(
        SourceChannel.output_orientation == "horizontal",
        sa.and_(
            SourceChannel.output_orientation == "auto",
            SourceChannel.reaction_source.is_(True),
        ),
    )


def vertical_only_condition():
    """SQL criterion matching vertical-only sources (horizontal file
    is deleted after the shorts extraction completes)."""
    return SourceChannel.output_orientation == "vertical"
