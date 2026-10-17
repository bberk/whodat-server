"""Declarative base for all ORM models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for ORM models.

    Models are added in milestone M2; Alembic reads `Base.metadata` to autogenerate migrations.
    """
