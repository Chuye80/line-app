from datetime import datetime, timedelta

import streamlit as st

from backend.models import Player, Game
from backend.team_generator import generate_balanced_teams


MAX_GAME_PLAYERS = 12


st.set_page_config(
    page_title="LineApp",
    page_icon="⚽",
    layout="centered",
)

st.title("⚽ LineApp")
st.subheader("Football Group Manager")


# --------------------------------------------------
# SESSION STATE
# --------------------------------------------------

if "players" not in st.session_state:
    st.session_state.players = []

if "game" not in st.session_state:
    st.session_state.game = None

if "teams" not in st.session_state:
    st.session_state.teams = None


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def is_priority_period() -> bool:
    """
    Returns True while registration is still reserved
    for subscribers.
    """
    if st.session_state.game is None:
        return False

    return (
        datetime.now()
        < st.session_state.game.regular_registration_opens
    )


def is_registered(player: Player) -> bool:
    if st.session_state.game is None:
        return False

    return player in st.session_state.game.participants


def is_waiting(player: Player) -> bool:
    if st.session_state.game is None:
        return False

    return player in st.session_state.game.waiting_list


def can_take_game_spot(player: Player) -> bool:
    """
    During subscriber-priority period:
        only subscribers can occupy game spots.

    After priority period:
        every member can occupy a game spot.
    """
    if is_priority_period():
        return player.is_subscriber

    return True


def promote_waiting_players() -> int:
    """
    Fill available game spots from the waiting list.

    During subscriber-priority period:
        only eligible subscribers may be promoted.

    After subscriber-priority period:
        players are promoted in FIFO order.

    Returns the number of players promoted.
    """

    game = st.session_state.game

    if game is None:
        return 0

    promoted_count = 0

    while (
        len(game.participants) < MAX_GAME_PLAYERS
        and game.waiting_list
    ):

        eligible_index = None

        for index, player in enumerate(
            game.waiting_list
        ):

            if can_take_game_spot(player):
                eligible_index = index
                break

        if eligible_index is None:
            break

        promoted_player = game.waiting_list.pop(
            eligible_index
        )

        game.participants.append(
            promoted_player
        )

        promoted_count += 1

    if promoted_count > 0:
        st.session_state.teams = None

    return promoted_count


def register_player(player: Player):
    game = st.session_state.game

    if game is None:
        return

    if player in game.participants:
        return

    if player in game.waiting_list:
        return

    if (
        len(game.participants) < MAX_GAME_PLAYERS
        and can_take_game_spot(player)
    ):
        game.participants.append(player)

    else:
        game.waiting_list.append(player)

    st.session_state.teams = None


def unregister_player(player: Player):
    game = st.session_state.game

    if game is None:
        return

    if player in game.participants:

        game.participants.remove(player)

        promote_waiting_players()

    elif player in game.waiting_list:

        game.waiting_list.remove(player)

    st.session_state.teams = None


# --------------------------------------------------
# AUTOMATIC PROMOTION CHECK
# --------------------------------------------------

# This runs every time the app itself reruns.
if st.session_state.game is not None:
    promote_waiting_players()


# --------------------------------------------------
# DEVELOPER TOOLS
# --------------------------------------------------

with st.sidebar.expander("Developer Tools"):

    if st.button("Add 12 Test Players"):

        st.session_state.players = [
            Player(
                "Shay",
                5,
                is_subscriber=True,
                is_virtual=True,
            ),
            Player(
                "Avi",
                5,
                is_subscriber=True,
                is_virtual=True,
            ),
            Player(
                "Dan",
                4,
                is_subscriber=True,
                is_virtual=True,
            ),
            Player(
                "Ron",
                4,
                is_subscriber=True,
                is_virtual=True,
            ),
            Player(
                "Gil",
                4,
                is_subscriber=True,
                is_virtual=True,
            ),
            Player(
                "Tom",
                4,
                is_subscriber=True,
                is_virtual=True,
            ),
            Player(
                "Yoni",
                3,
                is_subscriber=True,
                is_virtual=True,
            ),
            Player(
                "Nir",
                3,
                is_subscriber=True,
                is_virtual=True,
            ),
            Player(
                "Omer",
                3,
                is_virtual=True,
            ),
            Player(
                "Itay",
                3,
                is_virtual=True,
            ),
            Player(
                "Lior",
                2,
                is_virtual=True,
            ),
            Player(
                "Ben",
                2,
                is_virtual=True,
            ),
        ]

        st.session_state.teams = None

        if st.session_state.game:
            st.session_state.game.participants = []
            st.session_state.game.waiting_list = []

        st.rerun()

    if st.button("Add 16 Test Players"):

        st.session_state.players = [
            Player("Shay", 5, is_subscriber=True),
            Player("Avi", 5, is_subscriber=True),
            Player("Dan", 4, is_subscriber=True),
            Player("Ron", 4, is_subscriber=True),
            Player("Gil", 4, is_subscriber=True),
            Player("Tom", 4, is_subscriber=True),
            Player("Yoni", 3, is_subscriber=True),
            Player("Nir", 3, is_subscriber=True),
            Player("Omer", 3),
            Player("Itay", 3),
            Player("Lior", 2),
            Player("Ben", 2),
            Player("Eli", 4),
            Player("Noam", 3),
            Player("Adam", 2),
            Player("Guy", 3),
        ]

        st.session_state.teams = None

        if st.session_state.game:
            st.session_state.game.participants = []
            st.session_state.game.waiting_list = []

        st.rerun()

    if st.button("Register First 12"):

        if st.session_state.game is None:
            st.warning("Create a game first.")

        else:

            st.session_state.game.participants = []
            st.session_state.game.waiting_list = []

            for player in st.session_state.players[:12]:
                register_player(player)

            st.rerun()

    if st.button("Clear All Players"):

        st.session_state.players = []
        st.session_state.teams = None

        if st.session_state.game:
            st.session_state.game.participants = []
            st.session_state.game.waiting_list = []

        st.rerun()


# --------------------------------------------------
# NEXT GAME
# --------------------------------------------------

st.header("Next Game")

if st.session_state.game is None:

    st.info("No game has been scheduled yet.")

    with st.form("create_game_form"):

        game_date = st.date_input(
            "Game date"
        )

        game_time = st.time_input(
            "Game time"
        )

        priority_hours = st.number_input(
            "Regular registration opens how many hours before the game?",
            min_value=0,
            max_value=168,
            value=24,
            step=1,
        )

        create_game = st.form_submit_button(
            "Create Game",
            type="primary",
        )

        if create_game:

            game_datetime = datetime.combine(
                game_date,
                game_time,
            )

            regular_registration_opens = (
                game_datetime
                - timedelta(
                    hours=priority_hours
                )
            )

            st.session_state.game = Game(
                game_datetime=game_datetime,
                regular_registration_opens=regular_registration_opens,
            )

            st.session_state.teams = None

            st.rerun()

else:

    game = st.session_state.game

    st.write(
        f"### "
        f"{game.game_datetime.strftime('%A, %d/%m/%Y')}"
    )

    st.write(
        f"**Kickoff:** "
        f"{game.game_datetime.strftime('%H:%M')}"
    )

    st.write(
        f"**Regular registration opens:** "
        f"{game.regular_registration_opens.strftime('%d/%m/%Y %H:%M')}"
    )

    # --------------------------------------------------
    # LIVE COUNTDOWN
    # --------------------------------------------------

    @st.fragment(run_every="1s")
    def show_registration_countdown():

        current_game = st.session_state.game

        if current_game is None:
            return

        now = datetime.now()

        remaining = (
            current_game.regular_registration_opens
            - now
        )

        if remaining.total_seconds() > 0:

            total_seconds = int(
                remaining.total_seconds()
            )

            days, remainder = divmod(
                total_seconds,
                86400,
            )

            hours, remainder = divmod(
                remainder,
                3600,
            )

            minutes, seconds = divmod(
                remainder,
                60,
            )

            if days > 0:

                countdown = (
                    f"{days}d "
                    f"{hours:02d}:"
                    f"{minutes:02d}:"
                    f"{seconds:02d}"
                )

            else:

                countdown = (
                    f"{hours:02d}:"
                    f"{minutes:02d}:"
                    f"{seconds:02d}"
                )

            st.warning(
                f"⏳ Subscribers-only period: "
                f"{countdown} remaining"
            )

        else:

            st.success(
                "✅ Registration is open "
                "to all members"
            )

            promoted_count = (
                promote_waiting_players()
            )

            if promoted_count > 0:

                st.rerun(
                    scope="app"
                )

    show_registration_countdown()

    st.write(
        f"**Registered:** "
        f"{len(game.participants)}"
        f"/{MAX_GAME_PLAYERS}"
    )

    st.write(
        f"**Waiting list:** "
        f"{len(game.waiting_list)}"
    )

    if st.button("Delete Game"):

        st.session_state.game = None
        st.session_state.teams = None

        st.rerun()


st.divider()


# --------------------------------------------------
# ADD PLAYER
# --------------------------------------------------

st.header("Group Members")

with st.form("add_player_form"):

    name = st.text_input(
        "Player name"
    )

    rating = st.selectbox(
        "Rating",
        options=[1, 2, 3, 4, 5],
        index=2,
    )

    is_subscriber = st.checkbox(
        "Subscriber"
    )

    submitted = st.form_submit_button(
        "Add Player"
    )

    if submitted:

        if not name.strip():

            st.error(
                "Player name is required."
            )

        else:

            player = Player(
                name=name.strip(),
                rating=rating,
                is_subscriber=is_subscriber,
                is_virtual=True,
            )

            st.session_state.players.append(
                player
            )

            st.session_state.teams = None

            st.rerun()


st.divider()


# --------------------------------------------------
# PLAYER LIST + REGISTRATION
# --------------------------------------------------

if not st.session_state.players:

    st.info(
        "No players have been added yet."
    )

else:

    for index, player in enumerate(
        st.session_state.players
    ):

        if is_registered(player):
            registration_status = (
                "Registered"
            )

        elif is_waiting(player):
            registration_status = (
                "Waiting list"
            )

        else:
            registration_status = (
                "Not registered"
            )

        subscriber_text = (
            "Subscriber"
            if player.is_subscriber
            else "Regular"
        )

        with st.expander(
            f"{player.name} — "
            f"Rating {player.rating} — "
            f"{subscriber_text} — "
            f"{registration_status}"
        ):

            if st.session_state.game is not None:

                if is_registered(player):

                    if st.button(
                        "Unregister",
                        key=f"unregister_{index}",
                    ):

                        unregister_player(player)

                        st.rerun()

                elif is_waiting(player):

                    if st.button(
                        "Leave Waiting List",
                        key=f"leave_waiting_{index}",
                    ):

                        unregister_player(player)

                        st.rerun()

                else:

                    if (
                        is_priority_period()
                        and not player.is_subscriber
                    ):

                        button_text = (
                            "Join Waiting List"
                        )

                        st.caption(
                            "Subscriber priority is active. "
                            "Regular members can only join "
                            "the waiting list."
                        )

                    elif (
                        len(
                            st.session_state
                            .game
                            .participants
                        )
                        < MAX_GAME_PLAYERS
                    ):

                        button_text = (
                            "Join Game"
                        )

                    else:

                        button_text = (
                            "Join Waiting List"
                        )

                    if st.button(
                        button_text,
                        key=f"register_{index}",
                    ):

                        register_player(player)

                        st.rerun()

            else:

                st.caption(
                    "Create a game before "
                    "registering players."
                )

            # ------------------------------------------
            # EDIT PLAYER
            # ------------------------------------------

            with st.form(
                f"edit_player_{index}"
            ):

                edited_name = st.text_input(
                    "Name",
                    value=player.name,
                )

                edited_rating = st.selectbox(
                    "Rating",
                    options=[
                        1,
                        2,
                        3,
                        4,
                        5,
                    ],
                    index=player.rating - 1,
                )

                edited_subscriber = (
                    st.checkbox(
                        "Subscriber",
                        value=(
                            player.is_subscriber
                        ),
                    )
                )

                save = (
                    st.form_submit_button(
                        "Save Changes"
                    )
                )

                if save:

                    if not edited_name.strip():

                        st.error(
                            "Player name "
                            "is required."
                        )

                    else:

                        player.name = (
                            edited_name.strip()
                        )

                        player.rating = (
                            edited_rating
                        )

                        player.is_subscriber = (
                            edited_subscriber
                        )

                        st.session_state.teams = (
                            None
                        )

                        promote_waiting_players()

                        st.rerun()

            if st.button(
                "Delete Player",
                key=f"delete_player_{index}",
            ):

                if st.session_state.game:
                    unregister_player(
                        player
                    )

                st.session_state.players.remove(
                    player
                )

                st.session_state.teams = None

                st.rerun()


st.write(
    f"**Group members: "
    f"{len(st.session_state.players)}**"
)


# --------------------------------------------------
# GAME REGISTRATION
# --------------------------------------------------

st.divider()

st.header("Game Registration")

if st.session_state.game is None:

    st.info(
        "No active game."
    )

else:

    game = st.session_state.game

    st.subheader(
        f"Registered Players "
        f"({len(game.participants)}"
        f"/{MAX_GAME_PLAYERS})"
    )

    if not game.participants:

        st.write(
            "No players registered yet."
        )

    else:

        for position, player in enumerate(
            game.participants,
            start=1,
        ):

            subscriber_icon = (
                "⭐"
                if player.is_subscriber
                else ""
            )

            st.write(
                f"{position}. "
                f"{player.name} "
                f"{subscriber_icon} "
                f"(Rating {player.rating})"
            )

    st.subheader(
        f"Waiting List "
        f"({len(game.waiting_list)})"
    )

    if not game.waiting_list:

        st.write(
            "Waiting list is empty."
        )

    else:

        for position, player in enumerate(
            game.waiting_list,
            start=1,
        ):

            st.write(
                f"{position}. "
                f"{player.name}"
            )


# --------------------------------------------------
# TEAM GENERATION
# --------------------------------------------------

st.divider()

st.header("Team Draw")

if (
    st.session_state.game is not None
    and len(
        st.session_state
        .game
        .participants
    )
    == MAX_GAME_PLAYERS
):

    if st.button(
        "Generate Teams",
        type="primary",
    ):

        st.session_state.teams = (
            generate_balanced_teams(
                st.session_state
                .game
                .participants
            )
        )

        st.rerun()

else:

    st.info(
        "Exactly 12 registered players "
        "are required to generate teams."
    )


if st.session_state.teams:

    for team in st.session_state.teams:

        st.subheader(
            f"{team.name} — "
            f"Total rating: "
            f"{team.total_rating}"
        )

        for player in team.players:

            st.write(
                f"⚽ {player.name} "
                f"({player.rating})"
            )

        st.write(
            f"Average rating: "
            f"{team.average_rating:.2f}"
        )