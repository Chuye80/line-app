from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    SmallInteger,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )

    display_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )

    name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
    )

    games: Mapped[list["Game"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
    )


class Membership(Base):
    __tablename__ = "memberships"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )

    group_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
    )

    user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
    )

    display_name: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    rating: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=3,
    )

    is_subscriber: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    group: Mapped["Group"] = relationship(
        back_populates="memberships"
    )


class JoinRequest(Base):
    __tablename__ = "join_requests"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )

    group_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
    )

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="pending",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class Game(Base):
    __tablename__ = "games"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )

    group_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
    )

    game_datetime: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    regular_registration_opens: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    group: Mapped["Group"] = relationship(
        back_populates="games"
    )

    registrations: Mapped[list["Registration"]] = relationship(
        back_populates="game",
        cascade="all, delete-orphan",
    )

    team_assignments: Mapped[list["TeamAssignment"]] = relationship(
        back_populates="game",
        cascade="all, delete-orphan",
    )


class Registration(Base):
    __tablename__ = "registrations"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )

    game_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=False,
    )

    membership_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    game: Mapped["Game"] = relationship(
        back_populates="registrations"
    )

    membership: Mapped["Membership"] = relationship()


class TeamAssignment(Base):
    __tablename__ = "team_assignments"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )

    game_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=False,
    )

    membership_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
    )

    team_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    game: Mapped["Game"] = relationship(
        back_populates="team_assignments"
    )

    membership: Mapped["Membership"] = relationship()
