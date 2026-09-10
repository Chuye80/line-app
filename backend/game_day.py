"""Match play, standings and statistics for a game day.

Everything in this module is *derived*. A match has no stored score and a player
has no stored goal tally: both are counted from `match_goals` rows, and the
standings and statistics tables are computed from those counts plus the team
assignments. There is deliberately no denormalised counter anywhere, so the
scoreboard, the league table and the statistics tables cannot drift apart or
disagree with the list of goals that produced them.

Query counts stay bounded. Loading a game day costs a fixed number of
statements regardless of how many matches, goals or players it involves,
because the rows are fetched in bulk and joined in memory.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import (
    MATCH_COMPLETED,
    MATCH_LIVE,
    MATCH_SCHEDULED,
    POINTS_FOR_DRAW,
    POINTS_FOR_LOSS,
    POINTS_FOR_WIN,
    TEAM_NAMES,
    Game,
    Match,
    MatchGoal,
    Membership,
    PlayerRating,
    TeamAssignment,
)


FORMER_MEMBER_NAME = "Former member"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def round_robin_pairs(teams: Sequence[str]) -> list[tuple[str, str]]:
    """Every team plays every other team once.

    With the three teams the generator produces this is A-B, A-C, B-C.
    """

    return [
        (home, away)
        for index, home in enumerate(teams)
        for away in teams[index + 1 :]
    ]


def create_fixtures(db: Session, game_id: UUID, teams: Sequence[str]) -> list[Match]:
    """Lay out the day's matches. Caller must hold the game lock."""

    matches = [
        Match(
            game_id=game_id,
            match_order=order,
            home_team=home,
            away_team=away,
            status=MATCH_SCHEDULED,
        )
        for order, (home, away) in enumerate(round_robin_pairs(teams), start=1)
    ]

    db.add_all(matches)

    return matches


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_matches(db: Session, game_id: UUID) -> list[Match]:
    return list(
        db.execute(
            select(Match)
            .where(Match.game_id == game_id)
            .order_by(Match.match_order)
        ).scalars()
    )


def lock_match(db: Session, match_id: UUID) -> Match | None:
    return db.execute(
        select(Match).where(Match.id == match_id).with_for_update()
    ).scalar_one_or_none()


def load_goals(db: Session, match_ids: Iterable[UUID]) -> list[MatchGoal]:
    ids = list(match_ids)

    if not ids:
        return []

    return list(
        db.execute(
            select(MatchGoal)
            .where(MatchGoal.match_id.in_(ids))
            .order_by(MatchGoal.created_at, MatchGoal.id)
        ).scalars()
    )


def load_assignments_for_games(
    db: Session,
    game_ids: Iterable[UUID],
) -> list[TeamAssignment]:
    ids = list(game_ids)

    if not ids:
        return []

    return list(
        db.execute(
            select(TeamAssignment).where(TeamAssignment.game_id.in_(ids))
        ).scalars()
    )


def load_matches_for_games(db: Session, game_ids: Iterable[UUID]) -> list[Match]:
    ids = list(game_ids)

    if not ids:
        return []

    return list(
        db.execute(
            select(Match)
            .where(Match.game_id.in_(ids))
            .order_by(Match.game_id, Match.match_order)
        ).scalars()
    )


# ---------------------------------------------------------------------------
# Scores
# ---------------------------------------------------------------------------


def goals_by_match(goals: Iterable[MatchGoal]) -> dict[UUID, list[MatchGoal]]:
    grouped: dict[UUID, list[MatchGoal]] = defaultdict(list)

    for goal in goals:
        grouped[goal.match_id].append(goal)

    return grouped


def match_score(match: Match, goals: Iterable[MatchGoal]) -> tuple[int, int]:
    """(home, away), counted from the goal rows credited to each team."""

    home = away = 0

    for goal in goals:
        if goal.team_name == match.home_team:
            home += 1
        elif goal.team_name == match.away_team:
            away += 1

    return home, away


# ---------------------------------------------------------------------------
# Standings
# ---------------------------------------------------------------------------


@dataclass
class TeamRecord:
    name: str
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against

    @property
    def points(self) -> int:
        return (
            self.wins * POINTS_FOR_WIN
            + self.draws * POINTS_FOR_DRAW
            + self.losses * POINTS_FOR_LOSS
        )

    @property
    def ranking_key(self) -> tuple[int, int, int]:
        """What the table is sorted on, and what a tie for the title means."""

        return (self.points, self.goal_difference, self.goals_for)


def build_records(
    teams: Sequence[str],
    matches: Sequence[Match],
    grouped_goals: dict[UUID, list[MatchGoal]],
) -> dict[str, TeamRecord]:
    """Team records from completed matches only.

    A match in progress has a live score but no result yet, so counting it
    would show a team as having won a game it might still lose.
    """

    records = {name: TeamRecord(name=name) for name in teams}

    for match in matches:
        if match.status != MATCH_COMPLETED:
            continue

        home = records.get(match.home_team)
        away = records.get(match.away_team)

        if home is None or away is None:
            continue

        home_goals, away_goals = match_score(match, grouped_goals.get(match.id, []))

        home.played += 1
        away.played += 1
        home.goals_for += home_goals
        home.goals_against += away_goals
        away.goals_for += away_goals
        away.goals_against += home_goals

        if home_goals > away_goals:
            home.wins += 1
            away.losses += 1
        elif away_goals > home_goals:
            away.wins += 1
            home.losses += 1
        else:
            home.draws += 1
            away.draws += 1

    return records


def rank_records(records: Iterable[TeamRecord]) -> list[tuple[int, TeamRecord]]:
    """Sort into table order and assign positions, sharing a tied position."""

    ordered = sorted(
        records,
        key=lambda item: (
            -item.points,
            -item.goal_difference,
            -item.goals_for,
            item.name,
        ),
    )

    ranked: list[tuple[int, TeamRecord]] = []
    previous_key: tuple[int, int, int] | None = None
    position = 0

    for index, record in enumerate(ordered, start=1):
        if record.ranking_key != previous_key:
            position = index
            previous_key = record.ranking_key

        ranked.append((position, record))

    return ranked


def serialize_standings(ranked: Sequence[tuple[int, TeamRecord]]) -> list[dict]:
    return [
        {
            "position": position,
            "team": record.name,
            "played": record.played,
            "wins": record.wins,
            "draws": record.draws,
            "losses": record.losses,
            "goals_for": record.goals_for,
            "goals_against": record.goals_against,
            "goal_difference": record.goal_difference,
            "points": record.points,
        }
        for position, record in ranked
    ]


def champion_teams(ranked: Sequence[tuple[int, TeamRecord]]) -> list[str]:
    """The team, or teams, that finished top.

    Co-champions are a real outcome: three teams playing each other once can
    finish level on points, goal difference and goals scored. Returning a list
    lets the completion screen say so instead of picking a winner arbitrarily.
    """

    if not ranked:
        return []

    best = ranked[0][1]

    # A day where nothing was completed has no champion to crown.
    if best.played == 0:
        return []

    return [
        record.name
        for _, record in ranked
        if record.ranking_key == best.ranking_key
    ]


# ---------------------------------------------------------------------------
# Player statistics
# ---------------------------------------------------------------------------


@dataclass
class PlayerRecord:
    membership_id: UUID
    game_days: set[UUID] = field(default_factory=set)
    matches: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals: int = 0
    assists: int = 0


def build_player_records(
    matches: Sequence[Match],
    grouped_goals: dict[UUID, list[MatchGoal]],
    assignments: Sequence[TeamAssignment],
) -> dict[UUID, PlayerRecord]:
    """Per-player totals across whichever game days were loaded.

    Goals and assists count as soon as they are recorded, including in a match
    still in progress, because a goal is a fact the moment it is added. Matches,
    wins, draws and losses only count completed matches, for the same reason the
    standings do.
    """

    records: dict[UUID, PlayerRecord] = {}

    def record_for(membership_id: UUID) -> PlayerRecord:
        if membership_id not in records:
            records[membership_id] = PlayerRecord(membership_id=membership_id)

        return records[membership_id]

    # Which players were on which team, for each game day.
    roster: dict[tuple[UUID, str], list[UUID]] = defaultdict(list)

    for assignment in assignments:
        roster[(assignment.game_id, assignment.team_name)].append(
            assignment.membership_id
        )

    for match in matches:
        for goal in grouped_goals.get(match.id, []):
            if goal.scorer_membership_id is not None:
                record_for(goal.scorer_membership_id).goals += 1

            if goal.assist_membership_id is not None:
                record_for(goal.assist_membership_id).assists += 1

        if match.status != MATCH_COMPLETED:
            continue

        home_goals, away_goals = match_score(match, grouped_goals.get(match.id, []))

        for team, own, other in (
            (match.home_team, home_goals, away_goals),
            (match.away_team, away_goals, home_goals),
        ):
            for membership_id in roster.get((match.game_id, team), []):
                record = record_for(membership_id)
                record.matches += 1
                record.game_days.add(match.game_id)

                if own > other:
                    record.wins += 1
                elif own < other:
                    record.losses += 1
                else:
                    record.draws += 1

    # A player who was assigned to a team counts as having taken part in the
    # day even if no match of theirs has finished yet.
    for assignment in assignments:
        record_for(assignment.membership_id).game_days.add(assignment.game_id)

    return records


def load_survey_averages(db: Session, group_id: UUID) -> dict[UUID, tuple[float, int]]:
    """Average survey rating and response count, per rated member."""

    rows = db.execute(
        select(
            PlayerRating.subject_membership_id,
            func.avg(PlayerRating.rating),
            func.count(),
        )
        .where(PlayerRating.group_id == group_id)
        .group_by(PlayerRating.subject_membership_id)
    ).all()

    return {row[0]: (float(row[1]), row[2]) for row in rows}


def serialize_player_statistics(
    records: dict[UUID, PlayerRecord],
    memberships: Sequence[Membership],
    display_names: dict[UUID, str],
    survey: dict[UUID, tuple[float, int]] | None = None,
    *,
    include_game_days: bool,
    only: set[UUID] | None = None,
) -> list[dict]:
    """One row per player, ordered as a statistics table should read.

    Sorted by goals, then assists, then wins, then name, so the top scorer is
    first rather than whoever happens to have been created first.

    A member with nothing recorded still gets a row of zeroes: their survey
    rating is a statistic in its own right, and a player who has yet to score
    should read as "0" rather than disappear from the table.
    """

    from backend.services import member_name

    rows = []

    for membership in memberships:
        if only is not None and membership.id not in only:
            continue

        record = records.get(membership.id) or PlayerRecord(
            membership_id=membership.id
        )

        row = {
            "membership_id": str(membership.id),
            "name": member_name(membership, display_names),
            "is_virtual": membership.user_id is None,
            "matches": record.matches,
            "wins": record.wins,
            "draws": record.draws,
            "losses": record.losses,
            "goals": record.goals,
            "assists": record.assists,
            "points": record.goals + record.assists,
            "admin_rating": membership.rating,
        }

        if include_game_days:
            row["game_days"] = len(record.game_days)

        if survey is not None:
            average, responses = survey.get(membership.id, (None, 0))
            row["survey_rating"] = average
            row["survey_responses"] = responses

        rows.append(row)

    rows.sort(
        key=lambda item: (
            -item["goals"],
            -item["assists"],
            -item["wins"],
            item["name"].lower(),
        )
    )

    return rows


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def serialize_match(
    match: Match,
    goals: Sequence[MatchGoal],
    memberships_by_id: dict[UUID, Membership],
    display_names: dict[UUID, str],
) -> dict:
    from backend.services import member_name

    def scorer_name_of(membership_id: UUID | None) -> str:
        """Every goal is recorded with a scorer, so a missing one has left."""

        membership = (
            memberships_by_id.get(membership_id) if membership_id else None
        )

        if membership is None:
            return FORMER_MEMBER_NAME

        return member_name(membership, display_names)

    def assist_name_of(membership_id: UUID | None) -> str | None:
        """An assist is optional, so a missing one is simply not credited."""

        if membership_id is None:
            return None

        membership = memberships_by_id.get(membership_id)

        if membership is None:
            return FORMER_MEMBER_NAME

        return member_name(membership, display_names)

    home_goals, away_goals = match_score(match, goals)

    return {
        "id": str(match.id),
        "match_order": match.match_order,
        "home_team": match.home_team,
        "away_team": match.away_team,
        "status": match.status,
        "home_score": home_goals,
        "away_score": away_goals,
        "started_at": match.started_at,
        "completed_at": match.completed_at,
        "goals": [
            {
                "id": str(goal.id),
                "team_name": goal.team_name,
                "scorer_membership_id": (
                    str(goal.scorer_membership_id)
                    if goal.scorer_membership_id
                    else None
                ),
                "scorer_name": scorer_name_of(goal.scorer_membership_id),
                "assist_membership_id": (
                    str(goal.assist_membership_id)
                    if goal.assist_membership_id
                    else None
                ),
                "assist_name": assist_name_of(goal.assist_membership_id),
            }
            for goal in goals
        ],
    }


def game_day_view(db: Session, game: Game, group_id: UUID) -> dict:
    """The whole live game day in a fixed number of queries."""

    from backend import services

    memberships = services.load_memberships(db, group_id)
    memberships_by_id = {item.id: item for item in memberships}
    display_names = services.load_display_names(
        db, [item.user_id for item in memberships if item.user_id is not None]
    )

    assignments = services.load_team_assignments(db, game.id)
    matches = load_matches(db, game.id)
    grouped_goals = goals_by_match(load_goals(db, [item.id for item in matches]))

    teams = [
        name
        for name in TEAM_NAMES
        if any(item.team_name == name for item in assignments)
    ]

    records = build_records(teams, matches, grouped_goals)
    ranked = rank_records(records.values())

    player_records = build_player_records(matches, grouped_goals, assignments)
    squad = {item.membership_id for item in assignments}

    current = next(
        (item for item in matches if item.status == MATCH_LIVE),
        None,
    )
    upcoming = next(
        (item for item in matches if item.status == MATCH_SCHEDULED),
        None,
    )

    return {
        "id": str(game.id),
        "status": game.status,
        "game_datetime": game.game_datetime,
        "started_at": game.started_at,
        "finished_at": game.finished_at,
        "teams": services.serialize_teams(
            assignments, memberships_by_id, display_names
        ),
        "matches": [
            serialize_match(
                item,
                grouped_goals.get(item.id, []),
                memberships_by_id,
                display_names,
            )
            for item in matches
        ],
        "current_match_id": str(current.id) if current else None,
        "next_match_id": str(upcoming.id) if upcoming else None,
        "standings": serialize_standings(ranked),
        "champions": champion_teams(ranked) if game.finished_at else [],
        "statistics": serialize_player_statistics(
            player_records,
            memberships,
            display_names,
            include_game_days=False,
            only=squad,
        ),
    }


def overall_statistics(db: Session, group_id: UUID) -> dict:
    """Accumulated statistics across every finished game day in the group."""

    from backend import services

    memberships = services.load_memberships(db, group_id)
    display_names = services.load_display_names(
        db, [item.user_id for item in memberships if item.user_id is not None]
    )

    finished = services.load_finished_games(db, group_id)
    game_ids = [item.id for item in finished]

    matches = load_matches_for_games(db, game_ids)
    grouped_goals = goals_by_match(load_goals(db, [item.id for item in matches]))
    assignments = load_assignments_for_games(db, game_ids)

    records = build_player_records(matches, grouped_goals, assignments)

    return {
        "game_days": len(finished),
        "players": serialize_player_statistics(
            records,
            memberships,
            display_names,
            load_survey_averages(db, group_id),
            include_game_days=True,
        ),
    }


def history(db: Session, group_id: UUID) -> list[dict]:
    """Finished game days with their champion and final table."""

    from backend import services

    finished = services.load_finished_games(db, group_id)
    game_ids = [item.id for item in finished]

    matches = load_matches_for_games(db, game_ids)
    grouped_goals = goals_by_match(load_goals(db, [item.id for item in matches]))
    assignments = load_assignments_for_games(db, game_ids)

    matches_by_game: dict[UUID, list[Match]] = defaultdict(list)

    for match in matches:
        matches_by_game[match.game_id].append(match)

    teams_by_game: dict[UUID, list[str]] = defaultdict(list)

    for assignment in assignments:
        if assignment.team_name not in teams_by_game[assignment.game_id]:
            teams_by_game[assignment.game_id].append(assignment.team_name)

    result = []

    for game in finished:
        day_matches = matches_by_game.get(game.id, [])
        teams = [name for name in TEAM_NAMES if name in teams_by_game.get(game.id, [])]
        ranked = rank_records(
            build_records(teams, day_matches, grouped_goals).values()
        )

        result.append(
            {
                "id": str(game.id),
                "game_datetime": game.game_datetime,
                "finished_at": game.finished_at,
                "champions": champion_teams(ranked),
                "standings": serialize_standings(ranked),
                "matches_played": sum(
                    1 for item in day_matches if item.status == MATCH_COMPLETED
                ),
                "goals": sum(
                    len(grouped_goals.get(item.id, [])) for item in day_matches
                ),
            }
        )

    return result


def survey_view(
    db: Session,
    group_id: UUID,
    rater: Membership,
) -> dict:
    """Everybody the current user can rate, plus what they rated before."""

    from backend import services

    memberships = services.load_memberships(db, group_id)
    display_names = services.load_display_names(
        db, [item.user_id for item in memberships if item.user_id is not None]
    )

    existing = {
        row[0]: row[1]
        for row in db.execute(
            select(PlayerRating.subject_membership_id, PlayerRating.rating).where(
                PlayerRating.rater_membership_id == rater.id
            )
        ).all()
    }

    return {
        "rater_membership_id": str(rater.id),
        "players": [
            {
                "membership_id": str(item.id),
                "name": services.member_name(item, display_names),
                "is_virtual": item.user_id is None,
                "my_rating": (
                    float(existing[item.id]) if item.id in existing else None
                ),
            }
            for item in memberships
            # The survey never lists the person filling it in.
            if item.id != rater.id
        ],
    }


def save_survey(
    db: Session,
    group_id: UUID,
    rater: Membership,
    ratings: dict[UUID, Decimal | float | None],
) -> None:
    """Upsert the rater's answers. A null value clears a previous answer."""

    from backend import services

    valid_subjects = {
        item.id
        for item in db.execute(
            select(Membership).where(Membership.group_id == group_id)
        ).scalars()
    }

    existing = {
        item.subject_membership_id: item
        for item in db.execute(
            select(PlayerRating).where(
                PlayerRating.rater_membership_id == rater.id
            )
        ).scalars()
    }

    for subject_id, value in ratings.items():
        if subject_id not in valid_subjects or subject_id == rater.id:
            continue

        current = existing.get(subject_id)

        if value is None:
            if current is not None:
                db.delete(current)

            continue

        if current is None:
            db.add(
                PlayerRating(
                    group_id=group_id,
                    rater_membership_id=rater.id,
                    subject_membership_id=subject_id,
                    rating=value,
                )
            )
        else:
            current.rating = value
            current.updated_at = services.now_utc()
