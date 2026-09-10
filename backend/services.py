"""Domain rules and data access.

Two themes run through this module.

**Correctness under concurrency.** Every mutation that depends on counting rows
(is there a free slot? is this the last admin?) first takes a row lock on the
game or the group it belongs to. Without that, two requests read the same count
and both act on it, which is how a twelve-player game ends up with thirteen
participants and how the last administrator walks out of a group. The database
constraints added in `supabase/migrations` are the backstop; the locks are what
turn a lost race into a correct outcome rather than an error page.

**Bounded query counts.** The read helpers load a group in a fixed number of
statements no matter how many members, registrations or teams it has. The
previous code walked lazy relationships and fetched one `profiles` row per
player per section of the response.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from backend.models import (
    GAME_FINISHED,
    GAME_LIVE,
    GAME_SCHEDULED,
    REGISTRATION_PARTICIPANT,
    REGISTRATION_WAITING,
    TEAM_NAMES,
    Game,
    Group,
    Membership,
    Profile,
    Registration,
    TeamAssignment,
)
from backend.team_generator import REQUIRED_PLAYERS


# Registration capacity is the same number the team generator needs, because a
# game is generated as three teams of four.
MAX_GAME_PLAYERS = REQUIRED_PLAYERS

FALLBACK_PLAYER_NAME = "Player"
FALLBACK_VIRTUAL_NAME = "Virtual Player"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def get_group(db: Session, group_id: UUID) -> Group | None:
    return db.get(Group, group_id)


def lock_group(db: Session, group_id: UUID) -> Group | None:
    """Serialise membership and schedule changes for one group."""

    return db.execute(
        select(Group).where(Group.id == group_id).with_for_update()
    ).scalar_one_or_none()


def load_memberships(db: Session, group_id: UUID) -> list[Membership]:
    return list(
        db.execute(
            select(Membership)
            .where(Membership.group_id == group_id)
            .order_by(Membership.created_at, Membership.id)
        ).scalars()
    )


def get_active_game(db: Session, group_id: UUID, *, lock: bool = False) -> Game | None:
    """The game day the group is currently working with, if any.

    A *live* game day stays current no matter what the clock says, which is the
    whole reason the status is stored: matches are played after kickoff, so a
    time-derived notion of "active" could never describe a day in progress.

    A *scheduled* game day stops being current once its kickoff passes, exactly
    as before, and a *finished* one is history and is never returned here. That
    is what stops a refresh from reopening a day whose champion is already
    decided.
    """

    statement = (
        select(Game)
        .where(
            Game.group_id == group_id,
            or_(
                Game.status == GAME_LIVE,
                and_(
                    Game.status == GAME_SCHEDULED,
                    Game.game_datetime > now_utc(),
                ),
            ),
        )
        # A day in progress outranks one that is merely scheduled.
        .order_by(
            (Game.status == GAME_LIVE).desc(),
            Game.game_datetime.desc(),
            Game.created_at.desc(),
        )
        .limit(1)
    )

    if lock:
        statement = statement.with_for_update()

    return db.execute(statement).scalar_one_or_none()


def get_open_game(db: Session, group_id: UUID, *, lock: bool = False) -> Game | None:
    """Any game day that is not finished, including one past its kickoff.

    `get_active_game` hides a scheduled day once kickoff passes, but scheduling
    a replacement still has to find it so the old row can be superseded rather
    than left behind.
    """

    statement = (
        select(Game)
        .where(
            Game.group_id == group_id,
            Game.status.in_((GAME_SCHEDULED, GAME_LIVE)),
        )
        .order_by(
            (Game.status == GAME_LIVE).desc(),
            Game.game_datetime.desc(),
            Game.created_at.desc(),
        )
        .limit(1)
    )

    if lock:
        statement = statement.with_for_update()

    return db.execute(statement).scalar_one_or_none()


def get_latest_game_day(db: Session, group_id: UUID) -> Game | None:
    """The game day the app should be showing.

    That is the open one if there is one, and otherwise the day that just
    finished, so the completion screen and its champion survive a refresh
    instead of vanishing the moment the day is over.
    """

    active = get_active_game(db, group_id)

    if active is not None:
        return active

    return db.execute(
        select(Game)
        .where(Game.group_id == group_id, Game.status == GAME_FINISHED)
        .order_by(Game.finished_at.desc(), Game.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def load_finished_games(db: Session, group_id: UUID) -> list[Game]:
    """Completed game days, most recent first. The source for history."""

    return list(
        db.execute(
            select(Game)
            .where(Game.group_id == group_id, Game.status == GAME_FINISHED)
            .order_by(Game.game_datetime.desc(), Game.created_at.desc())
        ).scalars()
    )


def load_registrations(db: Session, game_id: UUID) -> list[Registration]:
    return list(
        db.execute(
            select(Registration)
            .where(Registration.game_id == game_id)
            .order_by(Registration.created_at, Registration.id)
        ).scalars()
    )


def load_team_assignments(db: Session, game_id: UUID) -> list[TeamAssignment]:
    return list(
        db.execute(
            select(TeamAssignment).where(TeamAssignment.game_id == game_id)
        ).scalars()
    )


def load_display_names(db: Session, user_ids: list[UUID]) -> dict[UUID, str]:
    """One query for every profile the response needs."""

    if not user_ids:
        return {}

    rows = db.execute(
        select(Profile.id, Profile.display_name).where(Profile.id.in_(set(user_ids)))
    ).all()

    return {row[0]: row[1] for row in rows}


def membership_for_user(
    db: Session,
    group_id: UUID,
    user_id: UUID,
) -> Membership | None:
    return db.execute(
        select(Membership).where(
            Membership.group_id == group_id,
            Membership.user_id == user_id,
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Registration rules
# ---------------------------------------------------------------------------


def split_registrations(
    registrations: list[Registration],
) -> tuple[list[Registration], list[Registration]]:
    """Participants and waiting list, both in registration order."""

    ordered = sorted(registrations, key=lambda item: (item.created_at, item.id))

    return (
        [item for item in ordered if item.status == REGISTRATION_PARTICIPANT],
        [item for item in ordered if item.status == REGISTRATION_WAITING],
    )


def is_priority_period(game: Game, at: datetime | None = None) -> bool:
    return (at or now_utc()) < game.regular_registration_opens


def can_take_game_spot(
    game: Game,
    membership: Membership,
    at: datetime | None = None,
) -> bool:
    """During the priority window only subscribers may take a playing slot."""

    if is_priority_period(game, at):
        return membership.is_subscriber

    return True


def clear_teams(db: Session, game_id: UUID) -> None:
    db.execute(delete(TeamAssignment).where(TeamAssignment.game_id == game_id))


def promote_waiting_players(
    db: Session,
    game: Game,
    memberships_by_id: dict[UUID, Membership] | None = None,
) -> bool:
    """Fill free slots from the waiting list, in order. Returns True if it did.

    Callers must already hold the lock on `game`.
    """

    registrations = load_registrations(db, game.id)
    participants, waiting = split_registrations(registrations)

    if memberships_by_id is None:
        memberships_by_id = {
            item.id: item for item in load_memberships(db, game.group_id)
        }

    promoted_any = False
    free_slots = MAX_GAME_PLAYERS - len(participants)

    for registration in waiting:
        if free_slots <= 0:
            break

        membership = memberships_by_id.get(registration.membership_id)

        if membership is None or not can_take_game_spot(game, membership):
            continue

        registration.status = REGISTRATION_PARTICIPANT
        free_slots -= 1
        promoted_any = True

    if promoted_any:
        clear_teams(db, game.id)

    return promoted_any


def waiting_players_can_be_promoted(
    game: Game,
    registrations: list[Registration],
    memberships_by_id: dict[UUID, Membership],
) -> bool:
    """Cheap read-only check used to avoid writing during GET requests."""

    participants, waiting = split_registrations(registrations)

    if len(participants) >= MAX_GAME_PLAYERS or not waiting:
        return False

    return any(
        (membership := memberships_by_id.get(item.membership_id)) is not None
        and can_take_game_spot(game, membership)
        for item in waiting
    )


# ---------------------------------------------------------------------------
# Administrator rules
# ---------------------------------------------------------------------------


def real_admins(memberships: list[Membership]) -> list[Membership]:
    """Administrators who have an account and can therefore actually sign in.

    Virtual players cannot be administrators (enforced by a check constraint),
    but counting defensively here keeps the rule true even for legacy rows.
    """

    return [
        item for item in memberships if item.is_admin and item.user_id is not None
    ]


def is_last_real_admin(memberships: list[Membership], membership: Membership) -> bool:
    admins = real_admins(memberships)

    return len(admins) == 1 and admins[0].id == membership.id


def group_has_real_members(memberships: list[Membership]) -> bool:
    return any(item.user_id is not None for item in memberships)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def member_name(membership: Membership, display_names: dict[UUID, str]) -> str:
    if membership.user_id is not None:
        return display_names.get(membership.user_id) or FALLBACK_PLAYER_NAME

    return membership.display_name or FALLBACK_VIRTUAL_NAME


def serialize_member(
    membership: Membership,
    display_names: dict[UUID, str],
) -> dict:
    return {
        "id": str(membership.id),
        "user_id": str(membership.user_id) if membership.user_id else None,
        "name": member_name(membership, display_names),
        "rating": membership.rating,
        "is_subscriber": membership.is_subscriber,
        "is_admin": membership.is_admin,
        "is_virtual": membership.user_id is None,
    }


def serialize_game(
    game: Game,
    registrations: list[Registration],
    memberships_by_id: dict[UUID, Membership],
    display_names: dict[UUID, str],
) -> dict:
    participants, waiting = split_registrations(registrations)

    def members(items: list[Registration]) -> list[dict]:
        return [
            serialize_member(memberships_by_id[item.membership_id], display_names)
            for item in items
            if item.membership_id in memberships_by_id
        ]

    return {
        "id": str(game.id),
        # The frontend switches between the registration, live and finished
        # experiences on this field alone.
        "status": game.status,
        "game_datetime": game.game_datetime,
        "regular_registration_opens": game.regular_registration_opens,
        "started_at": game.started_at,
        "finished_at": game.finished_at,
        "participants": members(participants),
        "waiting_list": members(waiting),
    }


def serialize_teams(
    assignments: list[TeamAssignment],
    memberships_by_id: dict[UUID, Membership],
    display_names: dict[UUID, str],
) -> list[dict]:
    by_team: dict[str, list[Membership]] = {name: [] for name in TEAM_NAMES}

    for assignment in assignments:
        membership = memberships_by_id.get(assignment.membership_id)

        if membership is not None and assignment.team_name in by_team:
            by_team[assignment.team_name].append(membership)

    result = []

    for name in TEAM_NAMES:
        members = by_team[name]

        if not members:
            continue

        total = sum(item.rating for item in members)

        result.append(
            {
                "name": name,
                "players": [
                    serialize_member(item, display_names) for item in members
                ],
                "total_rating": total,
                "average_rating": total / len(members),
            }
        )

    return result


def public_group_view(group: Group) -> dict:
    """What a signed-in non-member is allowed to see about a group.

    Enough to render the "request to join" screen, and nothing about who is in
    the group, how they are rated or when they play.
    """

    return {
        "id": str(group.id),
        "name": group.name,
        "members": [],
        "game": None,
        "teams": [],
    }


def game_detail(db: Session, group_id: UUID) -> dict | None:
    """Just the upcoming game, for endpoints that only changed the game.

    Mutating endpoints used to answer with the entire group - roster, teams and
    all - and then throw away everything but this field.
    """

    game = get_active_game(db, group_id)

    if game is None:
        return None

    memberships = load_memberships(db, group_id)
    memberships_by_id = {item.id: item for item in memberships}

    display_names = load_display_names(
        db,
        [item.user_id for item in memberships if item.user_id is not None],
    )

    return serialize_game(
        game,
        load_registrations(db, game.id),
        memberships_by_id,
        display_names,
    )


def group_detail(db: Session, group: Group) -> dict:
    """Full group state in a fixed number of queries.

    Memberships are resolved from a single in-memory map rather than through
    the `Registration.membership` / `TeamAssignment.membership` relationships,
    which would each trigger their own load.
    """

    # Read the identity out before any commit below, which would expire the
    # instance and cost an extra round-trip to read it back.
    group_id = group.id
    group_name = group.name

    memberships = load_memberships(db, group_id)
    memberships_by_id = {item.id: item for item in memberships}

    display_names = load_display_names(
        db,
        [item.user_id for item in memberships if item.user_id is not None],
    )

    game = get_active_game(db, group_id)

    registrations: list[Registration] = []
    assignments: list[TeamAssignment] = []
    game_snapshot: dict | None = None

    if game is not None:
        game_id = game.id
        registrations = load_registrations(db, game_id)

        # Time-based promotion is the one write a read may need to perform: the
        # priority window can expire with nobody touching the app. Do it only
        # when it would actually change something, so a steady-state poll stays
        # read-only. Once the day is live the squad is fixed, so there is
        # nothing to promote into.
        if game.status == GAME_SCHEDULED and waiting_players_can_be_promoted(
            game, registrations, memberships_by_id
        ):
            locked = get_active_game(db, group_id, lock=True)

            if locked is not None and promote_waiting_players(
                db, locked, memberships_by_id
            ):
                db.commit()

            memberships = load_memberships(db, group_id)
            memberships_by_id = {item.id: item for item in memberships}
            registrations = load_registrations(db, game_id)
            game = get_active_game(db, group_id)

        if game is not None:
            assignments = load_team_assignments(db, game_id)
            game_snapshot = serialize_game(
                game, registrations, memberships_by_id, display_names
            )

    return {
        "id": str(group_id),
        "name": group_name,
        "members": [
            serialize_member(item, display_names) for item in memberships
        ],
        "game": game_snapshot,
        "teams": serialize_teams(assignments, memberships_by_id, display_names),
    }
