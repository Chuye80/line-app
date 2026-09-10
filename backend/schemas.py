"""Request bodies.

Validation lives here rather than inside the route handlers so that malformed
input is rejected before it can reach a transaction.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.models import TEAM_NAMES


class CreateGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()

        if not stripped:
            raise ValueError("Group name cannot be blank")

        return stripped


class CreateGameRequest(BaseModel):
    game_datetime: datetime
    priority_hours: int = Field(ge=0, le=168)


class MemberRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    rating: int = Field(ge=1, le=5)
    is_subscriber: bool = False
    is_admin: bool = False

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()

        if not stripped:
            raise ValueError("Name cannot be blank")

        return stripped


class TeamAssignmentRequest(BaseModel):
    membership_id: UUID
    team_name: str

    @field_validator("team_name")
    @classmethod
    def _known_team(cls, value: str) -> str:
        if value not in TEAM_NAMES:
            raise ValueError(f"team_name must be one of {', '.join(TEAM_NAMES)}")

        return value


class UpdateTeamsRequest(BaseModel):
    assignments: list[TeamAssignmentRequest]


class AddGoalRequest(BaseModel):
    """A goal, credited to a team, a scorer and optionally an assist.

    The assist is optional because plenty of goals do not have one; the UI
    offers "No assist". That a player cannot assist his own goal is enforced
    here, in the route (which also checks both players are on the scoring team)
    and by a check constraint.
    """

    team_name: str
    scorer_membership_id: UUID
    assist_membership_id: UUID | None = None

    @field_validator("team_name")
    @classmethod
    def _known_team(cls, value: str) -> str:
        if value not in TEAM_NAMES:
            raise ValueError(f"team_name must be one of {', '.join(TEAM_NAMES)}")

        return value

    @model_validator(mode="after")
    def _assist_is_not_scorer(self) -> "AddGoalRequest":
        if (
            self.assist_membership_id is not None
            and self.assist_membership_id == self.scorer_membership_id
        ):
            raise ValueError("A player cannot assist their own goal")

        return self


# 1.0 to 5.0 in half-point steps, matching the half-star control in the survey.
SURVEY_RATING_STEP = Decimal("0.5")
SURVEY_RATING_MIN = Decimal("1.0")
SURVEY_RATING_MAX = Decimal("5.0")


class SurveyRatingRequest(BaseModel):
    membership_id: UUID
    # None clears a previously submitted answer.
    rating: Decimal | None = None

    @field_validator("rating")
    @classmethod
    def _half_steps_only(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None

        if value < SURVEY_RATING_MIN or value > SURVEY_RATING_MAX:
            raise ValueError("rating must be between 1.0 and 5.0")

        if value % SURVEY_RATING_STEP != 0:
            raise ValueError("rating must be a whole or half point")

        return value


class SaveSurveyRequest(BaseModel):
    ratings: list[SurveyRatingRequest]
