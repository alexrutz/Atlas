"""Pydantic Schemas für Gruppen."""

from datetime import datetime

from pydantic import BaseModel


class GroupCreate(BaseModel):
    name: str
    description: str | None = None


class GroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class GroupResponse(BaseModel):
    id: int
    name: str
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class GroupWithMembers(GroupResponse):
    members: list["MemberBrief"] = []


class MemberBrief(BaseModel):
    id: int
    username: str
    full_name: str

    model_config = {"from_attributes": True}


class MemberAssignment(BaseModel):
    user_ids: list[int]
