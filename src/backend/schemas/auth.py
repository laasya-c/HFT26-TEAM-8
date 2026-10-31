"""Authentication Request and Response Pydantic Schemas."""
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    """Credentials payload for POST /api/v1/auth/login."""
    model_config = ConfigDict(extra="forbid")

    username_or_email: str = Field(..., min_length=3, max_length=255, description="Registered username or email address")
    password: str = Field(..., min_length=1, max_length=255, description="Plaintext password")


class RefreshTokenRequest(BaseModel):
    """Optional JSON payload for POST /api/v1/auth/refresh when cookies are not utilized."""
    model_config = ConfigDict(extra="forbid")

    refresh_token: Optional[str] = Field(None, min_length=10, max_length=512, description="Plaintext refresh token")


class UserProfileResponse(BaseModel):
    """Public user profile model returned in auth responses."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    email: str
    role: str
    full_name: Optional[str] = None
    is_active: bool
    created_at: Optional[str] = None


class TokenResponseData(BaseModel):
    """Standard access token response envelope data."""
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    user: Optional[UserProfileResponse] = None
