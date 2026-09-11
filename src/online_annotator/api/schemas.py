"""Request bodies. Responses are plain dicts built by the ``serialize`` helpers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LoginBody(BaseModel):
    email: str
    password: str


class OtpRequestBody(BaseModel):
    email: str


class OtpVerifyBody(BaseModel):
    challenge_id: str
    code: str


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


class UserCreateBody(BaseModel):
    email: str
    full_name: str = Field(min_length=1, max_length=255)
    role: Literal["annotator", "reviewer", "admin"] = "annotator"
    password: str | None = None


class UserUpdateBody(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: Literal["annotator", "reviewer", "admin"] | None = None
    is_active: bool | None = None


class ClassBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str | None = None
    description: str = ""
    index: int | None = None


class ClassUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = None
    description: str | None = None


class ProjectCreateBody(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = ""
    guidelines: str = ""
    classes: list[ClassBody] = Field(default_factory=list)


class ProjectUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    guidelines: str | None = None
    archived: bool | None = None


class ImageUpdateBody(BaseModel):
    split: Literal["unassigned", "train", "val", "test"] | None = None
    assigned_to: str | None = None
    notes: str | None = None


class BulkImageUpdateBody(BaseModel):
    image_ids: list[int]
    split: Literal["unassigned", "train", "val", "test"] | None = None
    assigned_to: str | None = None


class SubmitBody(BaseModel):
    note: str = ""


class ReviewBody(BaseModel):
    decision: Literal["approve", "request_changes"]
    comment: str = ""


class ExportBody(BaseModel):
    layout: Literal["hydride_pairs", "split_folders"] = "hydride_pairs"
    mask_style: Literal["binary", "red", "indexed", "colour"] = "binary"
    target_class: int | None = None
    include: Literal["approved", "approved_and_submitted"] = "approved"
    split_mode: Literal["assigned", "auto"] = "assigned"
    train: float = Field(default=0.8, ge=0, le=1)
    val: float = Field(default=0.1, ge=0, le=1)
    test: float = Field(default=0.1, ge=0, le=1)
    seed: int = 42
    include_coco: bool = True
    include_yolo: bool = False
