"""Readiness proves database access and schema compatibility, without executing work."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


def database_ready(session: Session) -> bool:
    expected = set(ScriptDirectory.from_config(Config(str(
        Path(__file__).resolve().parents[1] / "alembic.ini"
    ))).get_heads())
    try:
        session.execute(text("SELECT 1"))
        actual = set(session.scalars(text("SELECT version_num FROM alembic_version")))
        return actual == expected
    except SQLAlchemyError:
        session.rollback()
        return False
