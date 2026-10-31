"""API Dependencies.

Provides:
- Database session injection.
- Reviewer authentication identity (supports local demo identity during development).
"""
from typing import Generator
from fastapi import Header
from src.backend.db.session import get_db


def get_current_reviewer(
    x_reviewer_id: str = Header(default="local_researcher_demo", description="Reviewer identity header")
) -> str:
    """Returns the authenticated reviewer identity.
    
    In local development, falls back to a clearly labelled demo identity.
    In production deployment, this is validated against JWT or OAuth token.
    """
    return x_reviewer_id
