from pydantic import BaseModel, Field


class CreateGroupRequest(BaseModel):
    name: str = Field(min_length=1)


class CreatePlayerRequest(BaseModel):
    name: str = Field(min_length=1)
    rating: int = Field(ge=1, le=5)
    is_subscriber: bool = False
    is_admin: bool = False
    is_virtual: bool = True