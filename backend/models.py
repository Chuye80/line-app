from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


def uuid_pk():
    return mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


def created_at_col() -> mapped_column:
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class Developer(Base):
    __tablename__ = "developers"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
    )
    created_at: Mapped[datetime] = created_at_col()


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    invite_code: Mapped[str] = mapped_column(Text, nullable=False)
    last_participant_count: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    last_players_per_team: Mapped[int] = mapped_column(Integer, nullable=False, default=4)

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
    )
    game_days: Mapped[list["GameDay"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
    )


class Membership(Base):
    __tablename__ = "memberships"

    id: Mapped[UUID] = uuid_pk()
    group_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    rating: Mapped[Decimal] = mapped_column(Numeric(3, 1), nullable=False, default=Decimal("3.0"))
    is_subscriber: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = created_at_col()

    group: Mapped["Group"] = relationship(back_populates="memberships")


class JoinRequest(Base):
    __tablename__ = "join_requests"

    id: Mapped[UUID] = uuid_pk()
    group_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    created_at: Mapped[datetime] = created_at_col()


class GameDay(Base):
    __tablename__ = "game_days"

    id: Mapped[UUID] = uuid_pk()
    group_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    game_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    regular_registration_opens: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = created_at_col()
    status: Mapped[str] = mapped_column(Text, nullable=False, default="upcoming")
    participant_count: Mapped[int] = mapped_column(Integer, nullable=False)
    players_per_team: Mapped[int] = mapped_column(Integer, nullable=False)
    is_rotating: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    champion_team_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    mvp_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    group: Mapped["Group"] = relationship(back_populates="game_days")
    registrations: Mapped[list["Registration"]] = relationship(
        back_populates="game_day",
        cascade="all, delete-orphan",
    )
    team_assignments: Mapped[list["TeamAssignment"]] = relationship(
        back_populates="game_day",
        cascade="all, delete-orphan",
    )
    matches: Mapped[list["Match"]] = relationship(
        back_populates="game_day",
        cascade="all, delete-orphan",
    )
    awards: Mapped[list["GameDayAward"]] = relationship(
        back_populates="game_day",
        cascade="all, delete-orphan",
    )
    mvp_votes: Mapped[list["MvpVote"]] = relationship(
        cascade="all, delete-orphan",
    )


class Registration(Base):
    __tablename__ = "registrations"

    id: Mapped[UUID] = uuid_pk()
    game_day_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("game_days.id", ondelete="CASCADE"),
        nullable=False,
    )
    membership_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at_col()

    game_day: Mapped["GameDay"] = relationship(back_populates="registrations")
    membership: Mapped["Membership"] = relationship()


class TeamAssignment(Base):
    __tablename__ = "team_assignments"

    id: Mapped[UUID] = uuid_pk()
    game_day_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("game_days.id", ondelete="CASCADE"),
        nullable=False,
    )
    membership_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
    )
    team_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    game_day: Mapped["GameDay"] = relationship(back_populates="team_assignments")
    membership: Mapped["Membership"] = relationship()


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[UUID] = uuid_pk()
    game_day_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("game_days.id", ondelete="CASCADE"),
        nullable=False,
    )
    home_team_name: Mapped[str] = mapped_column(Text, nullable=False)
    away_team_name: Mapped[str] = mapped_column(Text, nullable=False)
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    created_at: Mapped[datetime] = created_at_col()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    game_day: Mapped["GameDay"] = relationship(back_populates="matches")
    players: Mapped[list["MatchPlayer"]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
    )
    goals: Mapped[list["MatchGoal"]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
    )


class MatchPlayer(Base):
    __tablename__ = "match_players"

    id: Mapped[UUID] = uuid_pk()
    match_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("matches.id", ondelete="CASCADE"),
        nullable=False,
    )
    membership_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
    )
    team_name: Mapped[str] = mapped_column(Text, nullable=False)

    match: Mapped["Match"] = relationship(back_populates="players")
    membership: Mapped["Membership"] = relationship()


class MatchGoal(Base):
    __tablename__ = "match_goals"

    id: Mapped[UUID] = uuid_pk()
    match_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("matches.id", ondelete="CASCADE"),
        nullable=False,
    )
    scorer_membership_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
    )
    assist_membership_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = created_at_col()

    match: Mapped["Match"] = relationship(back_populates="goals")
    scorer: Mapped["Membership"] = relationship(foreign_keys=[scorer_membership_id])
    assister: Mapped["Membership | None"] = relationship(foreign_keys=[assist_membership_id])


class MvpVote(Base):
    __tablename__ = "mvp_votes"
    __table_args__ = (UniqueConstraint("game_day_id", "voter_membership_id"),)

    id: Mapped[UUID] = uuid_pk()
    game_day_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("game_days.id", ondelete="CASCADE"),
        nullable=False,
    )
    voter_membership_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
    )
    nominee_membership_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = created_at_col()


class GameDayAward(Base):
    __tablename__ = "game_day_awards"

    id: Mapped[UUID] = uuid_pk()
    game_day_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("game_days.id", ondelete="CASCADE"),
        nullable=False,
    )
    membership_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
    )
    award_type: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at_col()

    game_day: Mapped["GameDay"] = relationship(back_populates="awards")
    membership: Mapped["Membership"] = relationship()


class RatingSurvey(Base):
    __tablename__ = "rating_surveys"

    id: Mapped[UUID] = uuid_pk()
    group_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    created_at: Mapped[datetime] = created_at_col()
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    responses: Mapped[list["RatingSurveyResponse"]] = relationship(
        back_populates="survey",
        cascade="all, delete-orphan",
    )


class RatingSurveyResponse(Base):
    __tablename__ = "rating_survey_responses"

    id: Mapped[UUID] = uuid_pk()
    survey_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("rating_surveys.id", ondelete="CASCADE"),
        nullable=False,
    )
    rater_membership_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
    )
    rated_membership_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
    )
    rating: Mapped[Decimal] = mapped_column(Numeric(2, 1), nullable=False)
    created_at: Mapped[datetime] = created_at_col()

    survey: Mapped["RatingSurvey"] = relationship(back_populates="responses")
