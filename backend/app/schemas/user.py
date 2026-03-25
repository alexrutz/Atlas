"""Pydantic Schemas für Benutzer."""

from datetime import datetime

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    full_name: str
    is_admin: bool = False


class UserUpdate(BaseModel):
    email: str | None = None
    full_name: str | None = None
    is_active: bool | None = None
    is_admin: bool | None = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    is_active: bool
    is_admin: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserWithGroups(UserResponse):
    groups: list["GroupBrief"] = []


class GroupBrief(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}
