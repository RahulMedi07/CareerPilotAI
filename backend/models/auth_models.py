"""Request and response shapes for accounts.

Nothing here carries a password hash, a salt or a session token outward. The
token is delivered once, as an httpOnly cookie, and never appears in a
response body -- a body is readable by JavaScript, which is the thing the
cookie flag exists to prevent.
"""

from typing import Optional

from pydantic import BaseModel, Field

__all__ = [
    "SignupRequest",
    "LoginRequest",
    "AccountResponse",
    "LogoutResponse",
]


class SignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    #: The floor is enforced again in ``utils.auth.validate_password``. This
    #: one is here so the error arrives as a 422 with a field name attached
    #: rather than as a generic 400.
    password: str = Field(min_length=8, max_length=1024)
    name: str = Field(default="", max_length=120)


class LoginRequest(BaseModel):
    #: No ``min_length`` on either field. A short password is wrong, not
    #: malformed, and rejecting it at the schema tells an attacker the length
    #: rule before they have guessed anything.
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)


class AccountResponse(BaseModel):
    user_id: str
    email: str
    name: str = ""
    created_date: Optional[str] = None
    last_login: Optional[str] = None


class LogoutResponse(BaseModel):
    status: str = "success"
    message: str = "Signed out"
