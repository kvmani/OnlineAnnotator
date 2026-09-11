from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginRequest(BaseModel):
    email: str = Field(..., description="Office email address")
    password: str = Field(..., min_length=4)

    @field_validator("email")
    @classmethod
    def validate_office_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if not EMAIL_REGEX.match(clean):
            raise ValueError("Invalid office email format. Username must be a valid email address.")
        return clean


class EmailOtpRequest(BaseModel):
    email: str = Field(..., description="Office email address")

    @field_validator("email")
    @classmethod
    def validate_office_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if not EMAIL_REGEX.match(clean):
            raise ValueError("Invalid office email format. Username must be a valid email address.")
        return clean


class EmailOtpRequestResponse(BaseModel):
    challenge_id: str
    message: str
    expires_in_seconds: int
    dev_otp: Optional[str] = None  # Included only when email delivery is disabled for dev/testing


class EmailOtpConfirmRequest(BaseModel):
    challenge_id: str
    otp: str = Field(..., min_length=6, max_length=6)


class UserProfileResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime


class LoginResponse(BaseModel):
    token: str
    user: UserProfileResponse
    message: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6)


class RegisterUserRequest(BaseModel):
    email: str
    full_name: str
    password: str = Field(..., min_length=6)
    role: str = "annotator"

    @field_validator("email")
    @classmethod
    def validate_office_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if not EMAIL_REGEX.match(clean):
            raise ValueError("Invalid office email format. Username must be a valid email address.")
        return clean
