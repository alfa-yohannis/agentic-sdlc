"""Shared test data and helpers. See agents/shared_context/test-contract.md."""

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent

DEMO_EMAIL = "user@example.com"
DEMO_PASSWORD = "green apple house"
OTHER_EMAIL = "other@example.com"
OTHER_PASSWORD = "blue river stone"
WRONG_PASSWORD = "red apple house"
UNKNOWN_EMAIL = "nobody@example.com"

# FR-9
MSG_EMAIL_EMPTY = "Please enter your email address."
MSG_EMAIL_INVALID = "Please enter a valid email address, for example name@example.com."
MSG_PASSWORD_EMPTY = "Please enter your password."
MSG_PASSWORD_INVALID = (
    "Your password must have at least 3 words separated by spaces, "
    "for example: green apple house."
)
# FR-16
MSG_TWO_LEFT = "Email or password is incorrect. You have 2 attempts left."
MSG_ONE_LEFT = "Email or password is incorrect. You have 1 attempt left."
# FR-22
MSG_TRY_AGAIN = "You can try logging in again."
# FR-28
MSG_SERVER_ERROR = "Something went wrong. Please try again later."


def msg_wait(seconds):
    """FR-21"""
    unit = "second" if seconds == 1 else "seconds"
    return f"Too many failed attempts. Please wait {seconds} {unit} before trying again."


class FakeClock:
    """Replaceable clock: tests move time forward instead of sleeping."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_email(local_len, total_len):
    """Build a syntactically valid email of exact lengths, with domain labels <= 63 chars."""
    local = "a" * local_len
    domain_len = total_len - local_len - 1
    tld = "com"
    remaining = domain_len - len(tld)
    labels = []
    while remaining > 0:
        # each label costs len(label) + 1 for its dot
        size = min(63, remaining - 1)
        if size < 1:
            # cannot fit a 0-char label: grow the previous label instead
            labels[-1] += "b"
            remaining -= 1
            continue
        labels.append("b" * size)
        remaining -= size + 1
    email = local + "@" + ".".join(labels) + "." + tld
    assert len(email) == total_len, (len(email), total_len)
    assert len(email.split("@")[0]) == local_len
    return email


# Section 3.1 examples, plus the length limits in VR-E2 and VR-E4
VALID_EMAILS = [
    "name@example.com",
    "  Name.Surname+tag@Mail.Example.co.id  ",
    "NAME@EXAMPLE.COM",
    "a_b%c-d@sub-domain.example.org",
    make_email(64, 254),
]
INVALID_EMAILS = [
    "name@example",
    "name.example.com",
    "name@@example.com",
    ".name@example.com",
    "name.@example.com",
    "na..me@example.com",
    "name@-example.com",
    "name@example-.com",
    "name@example.c",
    "name@example.c0m",
    "name @example.com",
    "name@",
    "@example.com",
    "name@exa_mple.com",
    make_email(65, 100),
    make_email(64, 255),
]
EMPTY_EMAILS = ["", "   "]

# Section 3.2 examples, plus the length limit in VR-P2
VALID_PASSWORDS = [
    "green apple house",
    "green apple house tree",
    "Gr33n! apple  house",
    " green apple house",
    "green apple house ",
    "a b c",
    "a" * 124 + " b c",  # exactly 128
]
INVALID_PASSWORDS = [
    "greenapplehouse",
    "green apple",
    "green  apple",
    " green apple ",
    "   ",
    "green\tapple\thouse",
    "green\napple\nhouse",
    "a" * 125 + " b c",  # 129
]
