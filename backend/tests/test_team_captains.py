from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest


@dataclass
class World:
    client: object
    admin: uuid.UUID
    shai: uuid.UUID
    group_id: str
    game_day_id: str
    members: dict[str, str] = field(default_factory=dict)

    def call(self, method: str, path: str, user: uuid.UUID | None = None, **kwargs):
        return self.client.request(
            method, path, headers={"X-Test-User": str(user or self.admin)}, **kwargs
        )

    def ok(self, method: str, path: str, user: uuid.UUID | None = None, **kwargs):
        response = self.call(method, path, user, **kwargs)
        assert response.status_code == 200, response.text
        return response.json()

    @property
    def gd_path(self) -> str:
        return f"/groups/{self.group_id}/game-days/{self.game_day_id}"

    def group(self) -> dict:
        return self.ok("GET", f"/groups/{self.group_id}")

    def game_day(self) -> dict:
        return self.group()["game_day"]

    def set_captain(self, team: str, member: str | None, user=None):
        return self.call(
            "PUT",
            f"{self.gd_path}/captain",
            user,
            json={"team_name": team, "membership_id": self.members[member] if member else None},
        )

    def team_of(self, game_day: dict, member: str) -> str | None:
        member_id = self.members[member]
        for team in game_day["teams"]:
            if any(player["id"] == member_id for player in team["players"]):
                return team["name"]
        return None

    def teammate(self, game_day: dict, member: str) -> str:
        team = self.team_of(game_day, member)
        for name, member_id in self.members.items():
            if name != member and self.team_of(game_day, name) == team:
                return name
        raise AssertionError(f"{member} has no teammate")

    def assignments(self, game_day: dict) -> dict[str, str | None]:
        return {name: self.team_of(game_day, name) for name in self.members}


def create_user(sql, name: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    with sql.cursor() as cur:
        cur.execute(
            "INSERT INTO auth.users (id, email, raw_user_meta_data) VALUES (%s, %s, %s)",
            (str(user_id), f"{user_id}@example.test", json.dumps({"display_name": name})),
        )
    return user_id


@pytest.fixture
def world(client, sql) -> World:
    admin = create_user(sql, "Admin")
    shai = create_user(sql, "Shai")
    w = World(client=client, admin=admin, shai=shai, group_id="", game_day_id="")
    w.group_id = w.ok("POST", "/groups", json={"name": "Captains FC"})["id"]
    with sql.cursor() as cur:
        cur.execute(
            """
            INSERT INTO memberships (group_id, user_id, rating, goalkeeper_rating, is_subscriber, is_admin)
            VALUES (%s, %s, 3, 3, false, false) RETURNING id
            """,
            (w.group_id, str(shai)),
        )
        w.members["Shai"] = str(cur.fetchone()[0])
    for name, rating in (("Daniel", 4), ("Noa", 2)):
        member = w.ok("POST", f"/groups/{w.group_id}/members", json={"name": name, "rating": rating})
        w.members[name] = member["id"]
    kickoff = datetime.now(timezone.utc) + timedelta(days=2)
    w.game_day_id = w.ok(
        "POST",
        f"/groups/{w.group_id}/game-days",
        json={
            "game_datetime": kickoff.isoformat(),
            "priority_hours": 168,
            "participant_count": 4,
            "players_per_team": 2,
        },
    )["id"]
    for name in ("Shai", "Daniel", "Noa"):
        w.ok("POST", f"{w.gd_path}/register/{w.members[name]}")
    guest_payload = w.ok("POST", f"{w.gd_path}/guests", json={"name": "Gil", "rating": 3})
    w.members["Gil"] = next(p["id"] for p in guest_payload["participants"] if p["name"] == "Gil")
    w.ok("POST", f"{w.gd_path}/generate-teams")
    return w


def start_live(w: World) -> None:
    w.ok("POST", f"{w.gd_path}/start")


def play_and_finish(w: World, winner: str) -> dict:
    """Plays one Team A vs Team B match won by `winner`, then finishes the day."""
    match = w.ok(
        "POST",
        f"{w.gd_path}/matches",
        json={"home_team_name": "Team A", "away_team_name": "Team B"},
    )["matches"][-1]
    w.ok(
        "POST",
        f"/groups/{w.group_id}/matches/{match['id']}/complete",
        json={"goals": [{"team_name": winner}]},
    )
    return w.ok("POST", f"{w.gd_path}/finish")


# --- schema ---------------------------------------------------------------


def test_schema_allows_one_captain_per_team_and_only_on_a_team(world, sql):
    gd = world.game_day()
    shai_team = world.team_of(gd, "Shai")
    mate = world.teammate(gd, "Shai")
    with sql.cursor() as cur:
        cur.execute(
            "UPDATE team_assignments SET is_captain = true WHERE game_day_id = %s AND membership_id = %s",
            (world.game_day_id, world.members["Shai"]),
        )
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute(
                "UPDATE team_assignments SET is_captain = true WHERE game_day_id = %s AND membership_id = %s",
                (world.game_day_id, world.members[mate]),
            )
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                "UPDATE team_assignments SET team_name = NULL WHERE game_day_id = %s AND membership_id = %s",
                (world.game_day_id, world.members["Shai"]),
            )
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                "UPDATE game_days SET team_captain_names = '[]'::jsonb WHERE id = %s",
                (world.game_day_id,),
            )
    assert world.game_day()["team_captain_names"] == {shai_team: "Shai"}


# --- defaults and payload shape --------------------------------------------


def test_no_captain_by_default_and_internal_names_unchanged(world):
    gd = world.game_day()
    assert [team["name"] for team in gd["teams"]] == ["Team A", "Team B"]
    assert all(team["captain_id"] is None for team in gd["teams"])
    assert gd["team_captain_names"] == {}


def test_game_day_payload_keeps_every_existing_field(world):
    gd = world.game_day()
    expected = {
        "id", "game_datetime", "regular_registration_opens", "status", "participant_count",
        "players_per_team", "is_rotating", "champion_team_name", "mvp_open", "mvp_announced",
        "votes_cast", "eligible_voters", "my_vote", "participants", "waiting_list", "teams",
        "unassigned", "complete_teams", "leftover_players", "matches", "standings", "awards",
        "team_captain_names",
    }
    assert expected <= set(gd)
    assert set(gd["teams"][0]) == {"name", "captain_id", "players", "total_rating", "average_rating"}


# --- selecting, changing, removing ------------------------------------------


def test_admin_sets_changes_and_removes_captain(world):
    gd = world.game_day()
    team = world.team_of(gd, "Daniel")
    mate = world.teammate(gd, "Daniel")

    assert world.set_captain(team, "Daniel").status_code == 200
    gd = world.game_day()
    by_name = {t["name"]: t for t in gd["teams"]}
    assert by_name[team]["captain_id"] == world.members["Daniel"]
    assert gd["team_captain_names"] == {team: "Daniel"}

    assert world.set_captain(team, mate).status_code == 200
    gd = world.game_day()
    by_name = {t["name"]: t for t in gd["teams"]}
    assert by_name[team]["captain_id"] == world.members[mate]
    assert gd["team_captain_names"] == {team: mate}

    assert world.set_captain(team, None).status_code == 200
    gd = world.game_day()
    assert all(t["captain_id"] is None for t in gd["teams"])
    assert gd["team_captain_names"] == {}


def test_each_team_has_its_own_captain(world):
    gd = world.game_day()
    team_a_player = next(n for n in world.members if world.team_of(gd, n) == "Team A")
    team_b_player = next(n for n in world.members if world.team_of(gd, n) == "Team B")
    world.set_captain("Team A", team_a_player)
    world.set_captain("Team B", team_b_player)
    assert world.game_day()["team_captain_names"] == {"Team A": team_a_player, "Team B": team_b_player}


def test_captain_must_be_assigned_to_that_team(world):
    gd = world.game_day()
    team = world.team_of(gd, "Shai")
    other = next(n for n in world.members if world.team_of(gd, n) not in (team, None))
    response = world.set_captain(team, other)
    assert response.status_code == 400
    assert "assigned to this team" in response.json()["detail"]
    assert world.set_captain("Team Z", "Shai").status_code == 404


def test_only_admins_can_change_captains(world):
    team = world.team_of(world.game_day(), "Shai")
    response = world.set_captain(team, "Shai", user=world.shai)
    assert response.status_code == 403
    assert world.game_day()["team_captain_names"] == {}


def test_guest_and_virtual_players_can_be_captains(world):
    gd = world.game_day()
    gil_team = world.team_of(gd, "Gil")
    other_team = "Team B" if gil_team == "Team A" else "Team A"
    # Gil's team holds one of the three members, so the other team holds a virtual player.
    virtual = next(n for n in ("Daniel", "Noa") if world.team_of(gd, n) == other_team)
    assert world.set_captain(gil_team, "Gil").status_code == 200
    assert world.set_captain(other_team, virtual).status_code == 200
    assert world.game_day()["team_captain_names"] == {gil_team: "Gil", other_team: virtual}


def test_live_name_follows_profile_rename_before_finish(world):
    team = world.team_of(world.game_day(), "Shai")
    world.set_captain(team, "Shai")
    world.ok("PUT", "/profile", user=world.shai, json={"display_name": "Shai Cohen"})
    assert world.game_day()["team_captain_names"] == {team: "Shai Cohen"}


# --- team edits, regeneration, registration changes ------------------------


def _swap_payload(world: World, gd: dict, a: str, b: str) -> dict:
    current = world.assignments(gd)
    current[a], current[b] = current[b], current[a]
    return {
        "assignments": [
            {"membership_id": world.members[name], "team_name": team}
            for name, team in current.items()
        ]
    }


def test_team_edit_keeps_captain_who_stays_on_team(world):
    gd = world.game_day()
    shai_team = world.team_of(gd, "Shai")
    world.set_captain(shai_team, "Shai")
    mate = world.teammate(gd, "Shai")
    other = next(n for n in world.members if world.team_of(gd, n) not in (shai_team, None))
    world.ok("PUT", f"{world.gd_path}/teams", json=_swap_payload(world, gd, mate, other))
    gd = world.game_day()
    assert world.team_of(gd, "Shai") == shai_team
    assert gd["team_captain_names"] == {shai_team: "Shai"}


def test_team_edit_removes_captaincy_when_captain_moves(world):
    gd = world.game_day()
    shai_team = world.team_of(gd, "Shai")
    world.set_captain(shai_team, "Shai")
    other = next(n for n in world.members if world.team_of(gd, n) not in (shai_team, None))
    world.ok("PUT", f"{world.gd_path}/teams", json=_swap_payload(world, gd, "Shai", other))
    gd = world.game_day()
    assert world.team_of(gd, "Shai") != shai_team
    assert all(t["captain_id"] is None for t in gd["teams"])
    assert gd["team_captain_names"] == {}


def test_team_edit_removes_captaincy_when_captain_unassigned(world):
    gd = world.game_day()
    shai_team = world.team_of(gd, "Shai")
    world.set_captain(shai_team, "Shai")
    payload = {
        "assignments": [
            {"membership_id": world.members[name], "team_name": None if name == "Shai" else team}
            for name, team in world.assignments(gd).items()
        ]
    }
    world.ok("PUT", f"{world.gd_path}/teams", json=payload)
    gd = world.game_day()
    assert world.members["Shai"] in [p["id"] for p in gd["unassigned"]]
    assert gd["team_captain_names"] == {}


def test_regenerating_teams_clears_captains(world):
    world.set_captain(world.team_of(world.game_day(), "Shai"), "Shai")
    world.ok("POST", f"{world.gd_path}/generate-teams")
    assert world.game_day()["team_captain_names"] == {}


def test_registration_change_clears_captains(world):
    world.set_captain(world.team_of(world.game_day(), "Shai"), "Shai")
    world.ok("POST", f"{world.gd_path}/unregister/{world.members['Noa']}")
    assert world.game_day()["teams"] == []
    world.ok("POST", f"{world.gd_path}/register/{world.members['Noa']}")
    world.ok("POST", f"{world.gd_path}/generate-teams")
    assert world.game_day()["team_captain_names"] == {}


# --- live and finished ------------------------------------------------------


def test_captain_can_change_while_live(world):
    start_live(world)
    gd = world.game_day()
    assert gd["status"] == "live"
    team = world.team_of(gd, "Daniel")
    assert world.set_captain(team, "Daniel").status_code == 200
    assert world.game_day()["team_captain_names"] == {team: "Daniel"}


def test_finish_snapshots_names_and_locks_captains(world):
    gd = world.game_day()
    shai_team = world.team_of(gd, "Shai")
    other_team = "Team B" if shai_team == "Team A" else "Team A"
    other_captain = next(n for n in ("Daniel", "Noa", "Gil") if world.team_of(gd, n) == other_team)
    world.set_captain(shai_team, "Shai")
    world.set_captain(other_team, other_captain)
    start_live(world)
    finished = play_and_finish(world, winner=shai_team)

    expected = {shai_team: "Shai", other_team: other_captain}
    assert finished["status"] == "finished"
    assert finished["team_captain_names"] == expected
    assert finished["champion_team_name"] == shai_team

    world.ok("PUT", "/profile", user=world.shai, json={"display_name": "Renamed Later"})
    group = world.group()
    assert group["game_day"] is None
    assert group["finished_game_day"]["team_captain_names"] == expected

    response = world.set_captain(shai_team, world.teammate(gd, "Shai"))
    assert response.status_code == 400
    assert "finished" in response.json()["detail"]
    assert world.call("POST", f"{world.gd_path}/generate-teams").status_code == 400
    assert world.call(
        "PUT", f"{world.gd_path}/teams", json=_swap_payload(world, gd, "Shai", other_captain)
    ).status_code == 400
    assert world.group()["finished_game_day"]["team_captain_names"] == expected


def test_finish_without_captains_snapshots_empty_map(world, sql):
    start_live(world)
    finished = play_and_finish(world, winner="Team A")
    assert finished["team_captain_names"] == {}
    with sql.cursor() as cur:
        cur.execute("SELECT team_captain_names FROM game_days WHERE id = %s", (world.game_day_id,))
        assert cur.fetchone()[0] == {}


def test_snapshot_survives_captain_membership_deletion(world, sql):
    gd = world.game_day()
    daniel_team = world.team_of(gd, "Daniel")
    world.set_captain(daniel_team, "Daniel")
    start_live(world)
    play_and_finish(world, winner="Team A")
    with sql.cursor() as cur:
        cur.execute("DELETE FROM memberships WHERE id = %s", (world.members["Daniel"],))
    assert world.group()["finished_game_day"]["team_captain_names"] == {daniel_team: "Daniel"}


def test_matches_goals_and_standings_keep_internal_identifiers(world):
    gd = world.game_day()
    world.set_captain(world.team_of(gd, "Shai"), "Shai")
    start_live(world)
    match = world.ok(
        "POST",
        f"{world.gd_path}/matches",
        json={"home_team_name": "Team A", "away_team_name": "Team B"},
    )["matches"][-1]
    assert (match["home_team_name"], match["away_team_name"]) == ("Team A", "Team B")
    assert {p["team_name"] for p in match["players"]} == {"Team A", "Team B"}
    done = world.ok(
        "POST",
        f"/groups/{world.group_id}/matches/{match['id']}/complete",
        json={"goals": [{"team_name": "Team B"}, {"team_name": "Team B"}]},
    )
    played = next(m for m in done["matches"] if m["id"] == match["id"])
    assert (played["home_score"], played["away_score"]) == (0, 2)
    assert [g["team_name"] for g in played["goals"]] == ["Team B", "Team B"]
    assert {row["name"] for row in done["standings"]} == {"Team A", "Team B"}
