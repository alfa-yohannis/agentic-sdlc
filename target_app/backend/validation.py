"""Server-side format rules VR-E (email) and VR-P (password), and the FR-9 messages.

The email pattern is the one in the specification, character for character, so the
page and the server accept exactly the same input. Use re.fullmatch: Python's `$`
alone would also match before a trailing newline.
"""

import re

EMAIL_PATTERN = (
    r"^[A-Za-z0-9_%+-]+(\.[A-Za-z0-9_%+-]+)*@([A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}$"
)

EMAIL_MAX_LENGTH = 254
EMAIL_LOCAL_MAX_LENGTH = 64
PASSWORD_MAX_LENGTH = 128
PASSWORD_MIN_WORDS = 3

MSG_EMAIL_EMPTY = "Please enter your email address."
MSG_EMAIL_INVALID = "Please enter a valid email address, for example name@example.com."
MSG_PASSWORD_EMPTY = "Please enter your password."
MSG_PASSWORD_INVALID = (
    "Your password must have at least 3 words separated by spaces, for example: green apple house."
)

_EMAIL_RE = re.compile(EMAIL_PATTERN)


def normalize_email(email: str) -> str:
    """Trim and lowercase."""
    return email.strip().lower()


def is_valid_email(email: str) -> bool:
    """VR-E1 to VR-E6, applied to the trimmed email."""
    if not isinstance(email, str):
        return False
    email = email.strip()
    if not email or len(email) > EMAIL_MAX_LENGTH:
        return False
    if _EMAIL_RE.fullmatch(email) is None:
        return False
    return len(email.split("@", 1)[0]) <= EMAIL_LOCAL_MAX_LENGTH


def is_valid_password(password: str) -> bool:
    """VR-P1 to VR-P4. Passwords are never trimmed; only U+0020 counts as a space."""
    if not isinstance(password, str):
        return False
    if not password or len(password) > PASSWORD_MAX_LENGTH:
        return False
    if password.count(" ") < PASSWORD_MIN_WORDS - 1:
        return False
    return len([w for w in password.split(" ") if w]) >= PASSWORD_MIN_WORDS


def email_error(email: str) -> str | None:
    """FR-9 message for the email field, or None when it is valid."""
    if is_valid_email(email):
        return None
    if not isinstance(email, str) or not email.strip():
        return MSG_EMAIL_EMPTY
    return MSG_EMAIL_INVALID


def password_error(password: str) -> str | None:
    """FR-9 message for the password field, or None when it is valid."""
    if is_valid_password(password):
        return None
    if not isinstance(password, str) or password == "":
        return MSG_PASSWORD_EMPTY
    return MSG_PASSWORD_INVALID
