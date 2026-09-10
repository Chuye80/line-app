"""SQLAlchemy models.

These mirror `supabase/migrations` exactly. The constraints, defaults and
indexes are declared here as well as in SQL so that the model layer is not a
lossy description of the database: `supabase/verify_schema.sql` checks the live
project against the same set, and the test suite creates its database from the
migrations, so a divergence between the two shows up as a test failure rather
than as a production surprise.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


_UUID_DEFAULT = text("gen_random_uuid()")
_NOW = text("now()")

TEAM_NAMES: tuple[str, ...] = ("Team A", "Team B", "Team C")

REGISTRATION_PARTICIPANT = "participant"
REGISTRATION_WAITING = "waiting"

JOIN_REQUEST_PENDING = "pending"
JOIN_REQUEST_APPROVED = "approved"
JOIN_REQUEST_DECLINED = "declined"

# Game day lifecycle. Stored rather than derived from the clock so that a
# finished day stays finished across a refresh.
GAME_SCHEDULED = "scheduled"
GAME_LIVE = "live"
GAME_FINISHED = "finished"

MATCH_SCHEDULED = "scheduled"
MATCH_LIVE = "live"
MATCH_COMPLETED = "completed"

# Football scoring, used to build the standings table.
POINTS_FOR_WIN = 3
POINTS_FOR_DRAW = 1
POINTS_FOR_LOSS = 0

_TEAM_NAME_CHECK = "in ('Team A', 'Team B', 'Team C')"


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)

    display_name: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=_NOW,
    )


class Group(Base):
    __tablename__ = "groups"
    __table_args__ = (
        CheckConstraint(
            "nullif(trim(name), '') is not null",
            name="groups_name_not_blank",
        ),
        Index("groups_created_at_idx", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=_UUID_DEFAULT,
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)

    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=_NOW,
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
    __table_args__ = (
        CheckConstraint(
            "rating between 1 and 5",
            name="memberships_rating_range",
        ),
        CheckConstraint(
            "user_id is not null "
            "or nullif(trim(coalesce(display_name, '')), '') is not null",
            name="memberships_identity_present",
        ),
        CheckConstraint(
            "user_id is not null or not is_admin",
            name="memberships_virtual_players_not_admin",
        ),
        Index(
            "memberships_group_user_unique",
            "group_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id is not null"),
        ),
        Index("memberships_group_id_idx", "group_id"),
        Index(
            "memberships_user_id_idx",
            "user_id",
            postgresql_where=text("user_id is not null"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=_UUID_DEFAULT,
    )

    group_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
    )

    user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    rating: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        server_default=text("3"),
        default=3,
    )

    is_subscriber: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
    )

    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=_NOW,
    )

    group: Mapped["Group"] = relationship(back_populates="memberships")

    @property
    def is_virtual(self) -> bool:
        return self.user_id is None


class JoinRequest(Base):
    __tablename__ = "join_requests"
    __table_args__ = (
        CheckConstraint(
            "status in ('pending', 'approved', 'declined')",
            name="join_requests_status_valid",
        ),
        Index(
            "join_requests_pending_unique",
            "group_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("join_requests_group_status_idx", "group_id", "status", "created_at"),
        Index("join_requests_user_idx", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=_UUID_DEFAULT,
    )

    group_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
    )

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'pending'"),
        default=JOIN_REQUEST_PENDING,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=_NOW,
    )


class Game(Base):
    """A game day: the fixture, its squad, its teams and its matches."""

    __tablename__ = "games"
    __table_args__ = (
        CheckConstraint(
            "regular_registration_opens <= game_datetime",
            name="games_priority_window_valid",
        ),
        CheckConstraint(
            "status in ('scheduled', 'live', 'finished')",
            name="games_status_valid",
        ),
        CheckConstraint(
            "(status = 'scheduled' and started_at is null "
            "and finished_at is null) "
            "or (status = 'live' and started_at is not null "
            "and finished_at is null) "
            "or (status = 'finished' and started_at is not null "
            "and finished_at is not null)",
            name="games_lifecycle_timestamps_valid",
        ),
        Index("games_group_datetime_idx", "group_id", "game_datetime"),
        Index(
            "games_group_status_idx",
            "group_id",
            "status",
            text("game_datetime desc"),
        ),
        Index(
            "games_one_live_per_group",
            "group_id",
            unique=True,
            postgresql_where=text("status = 'live'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=_UUID_DEFAULT,
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

    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'scheduled'"),
        default=GAME_SCHEDULED,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=_NOW,
    )

    group: Mapped["Group"] = relationship(back_populates="games")

    registrations: Mapped[list["Registration"]] = relationship(
        back_populates="game",
        cascade="all, delete-orphan",
    )

    team_assignments: Mapped[list["TeamAssignment"]] = relationship(
        back_populates="game",
        cascade="all, delete-orphan",
    )

    matches: Mapped[list["Match"]] = relationship(
        back_populates="game",
        cascade="all, delete-orphan",
    )


class Registration(Base):
    __tablename__ = "registrations"
    __table_args__ = (
        CheckConstraint(
            "status in ('participant', 'waiting')",
            name="registrations_status_valid",
        ),
        Index(
            "registrations_game_membership_unique",
            "game_id",
            "membership_id",
            unique=True,
        ),
        Index("registrations_game_status_idx", "game_id", "status", "created_at"),
        Index("registrations_membership_idx", "membership_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=_UUID_DEFAULT,
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

    status: Mapped[str] = mapped_column(Text, nullable=False)

    # clock_timestamp() rather than now(): now() is the transaction timestamp,
    # so several registrations written by one transaction would tie and the
    # waiting list order would be arbitrary.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )

    game: Mapped["Game"] = relationship(back_populates="registrations")

    membership: Mapped["Membership"] = relationship()


class TeamAssignment(Base):
    __tablename__ = "team_assignments"
    __table_args__ = (
        CheckConstraint(
            "team_name in ('Team A', 'Team B', 'Team C')",
            name="team_assignments_team_name_valid",
        ),
        Index(
            "team_assignments_game_membership_unique",
            "game_id",
            "membership_id",
            unique=True,
        ),
        Index("team_assignments_game_idx", "game_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=_UUID_DEFAULT,
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

    team_name: Mapped[str] = mapped_column(Text, nullable=False)

    game: Mapped["Game"] = relationship(back_populates="team_assignments")

    membership: Mapped["Membership"] = relationship()


class Match(Base):
    """One fixture inside a game day, e.g. Team A against Team B.

    The score is not stored. It is counted from `MatchGoal` rows so the goal
    list and the scoreboard cannot disagree.
    """

    __tablename__ = "matches"
    __table_args__ = (
        CheckConstraint(
            f"home_team {_TEAM_NAME_CHECK} and away_team {_TEAM_NAME_CHECK}",
            name="matches_teams_known",
        ),
        CheckConstraint("home_team <> away_team", name="matches_teams_distinct"),
        CheckConstraint(
            "status in ('scheduled', 'live', 'completed')",
            name="matches_status_valid",
        ),
        CheckConstraint(
            "(status = 'scheduled' and started_at is null "
            "and completed_at is null) "
            "or (status = 'live' and started_at is not null "
            "and completed_at is null) "
            "or (status = 'completed' and started_at is not null "
            "and completed_at is not null)",
            name="matches_lifecycle_timestamps_valid",
        ),
        Index("matches_game_order_unique", "game_id", "match_order", unique=True),
        Index(
            "matches_one_live_per_game",
            "game_id",
            unique=True,
            postgresql_where=text("status = 'live'"),
        ),
        Index("matches_game_idx", "game_id", "match_order"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=_UUID_DEFAULT,
    )

    game_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=False,
    )

    match_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    home_team: Mapped[str] = mapped_column(Text, nullable=False)

    away_team: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'scheduled'"),
        default=MATCH_SCHEDULED,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=_NOW,
    )

    game: Mapped["Game"] = relationship(back_populates="matches")

    goals: Mapped[list["MatchGoal"]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
    )


class MatchGoal(Base):
    """A goal, credited to a team and optionally to a scorer and an assist.

    `team_name` is stored rather than derived from the scorer's team assignment.
    That is what allows a member to be removed from the group later without
    rewriting the result of a match that has already been played: the scorer
    reference is cleared and the goal, and therefore the score, survives.
    """

    __tablename__ = "match_goals"
    __table_args__ = (
        CheckConstraint(
            f"team_name {_TEAM_NAME_CHECK}",
            name="match_goals_team_known",
        ),
        CheckConstraint(
            "assist_membership_id is null "
            "or scorer_membership_id is null "
            "or assist_membership_id <> scorer_membership_id",
            name="match_goals_assist_is_not_scorer",
        ),
        Index("match_goals_match_idx", "match_id", "created_at"),
        Index(
            "match_goals_scorer_idx",
            "scorer_membership_id",
            postgresql_where=text("scorer_membership_id is not null"),
        ),
        Index(
            "match_goals_assist_idx",
            "assist_membership_id",
            postgresql_where=text("assist_membership_id is not null"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=_UUID_DEFAULT,
    )

    match_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("matches.id", ondelete="CASCADE"),
        nullable=False,
    )

    team_name: Mapped[str] = mapped_column(Text, nullable=False)

    scorer_membership_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="SET NULL"),
        nullable=True,
    )

    assist_membership_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="SET NULL"),
        nullable=True,
    )

    # clock_timestamp() so several goals added in one transaction still order.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )

    match: Mapped["Match"] = relationship(back_populates="goals")


class PlayerRating(Base):
    """One member's rating of another, from the rating survey.

    Keyed on (rater, subject) so reopening the survey shows what was submitted
    before and saving again updates rather than accumulates.
    """

    __tablename__ = "player_ratings"
    __table_args__ = (
        CheckConstraint(
            "rating >= 1.0 and rating <= 5.0 and mod(rating * 2, 1) = 0",
            name="player_ratings_value_valid",
        ),
        CheckConstraint(
            "rater_membership_id <> subject_membership_id",
            name="player_ratings_no_self_rating",
        ),
        Index(
            "player_ratings_rater_subject_unique",
            "rater_membership_id",
            "subject_membership_id",
            unique=True,
        ),
        Index("player_ratings_subject_idx", "subject_membership_id"),
        Index("player_ratings_group_idx", "group_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=_UUID_DEFAULT,
    )

    group_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
    )

    rater_membership_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
    )

    subject_membership_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
    )

    rating: Mapped[float] = mapped_column(Numeric(2, 1), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=_NOW,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=_NOW,
    )
