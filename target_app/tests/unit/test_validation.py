"""Section 3 (VR-E, VR-P) and FR-9 messages: server-side rules in backend/validation.py."""

import importlib

import pytest

from tests.helpers import (
    EMPTY_EMAILS,
    INVALID_EMAILS,
    INVALID_PASSWORDS,
    MSG_EMAIL_EMPTY,
    MSG_EMAIL_INVALID,
    MSG_PASSWORD_EMPTY,
    MSG_PASSWORD_INVALID,
    VALID_EMAILS,
    VALID_PASSWORDS,
    make_email,
)

SPEC_EMAIL_PATTERN = (
    r"^[A-Za-z0-9_%+-]+(\.[A-Za-z0-9_%+-]+)*@([A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}$"
)


@pytest.fixture
def validation():
    return importlib.import_module("backend.validation")


def test_vr_e_email_pattern_matches_spec(validation):
    assert validation.EMAIL_PATTERN == SPEC_EMAIL_PATTERN


@pytest.mark.parametrize("email", VALID_EMAILS)
def test_vr_e_valid_email_accepted(validation, email):
    assert validation.is_valid_email(email) is True
    assert validation.email_error(email) is None


@pytest.mark.parametrize("email", INVALID_EMAILS)
def test_vr_e2_to_e6_invalid_email_rejected(validation, email):
    assert validation.is_valid_email(email) is False
    assert validation.email_error(email) == MSG_EMAIL_INVALID


@pytest.mark.parametrize("email", EMPTY_EMAILS)
def test_vr_e1_empty_email_rejected(validation, email):
    assert validation.is_valid_email(email) is False
    assert validation.email_error(email) == MSG_EMAIL_EMPTY


def test_vr_e4_local_part_max_64(validation):
    assert validation.is_valid_email(make_email(64, 100)) is True
    assert validation.is_valid_email(make_email(65, 100)) is False


def test_vr_e2_email_max_254(validation):
    assert validation.is_valid_email(make_email(10, 254)) is True
    assert validation.is_valid_email(make_email(10, 255)) is False


def test_vr_e_trailing_newline_does_not_sneak_past_pattern(validation):
    # Python's "$" matches before a final "\n"; the pattern must use fullmatch
    assert validation.is_valid_email("name@example.com\nx") is False


def test_vr_e_normalize_email_trims_and_lowercases(validation):
    assert validation.normalize_email("  User@Example.COM ") == "user@example.com"


@pytest.mark.parametrize("password", VALID_PASSWORDS)
def test_vr_p_valid_password_accepted(validation, password):
    assert validation.is_valid_password(password) is True
    assert validation.password_error(password) is None


@pytest.mark.parametrize("password", INVALID_PASSWORDS)
def test_vr_p2_to_p4_invalid_password_rejected(validation, password):
    assert validation.is_valid_password(password) is False
    assert validation.password_error(password) == MSG_PASSWORD_INVALID


def test_vr_p1_empty_password_rejected(validation):
    assert validation.is_valid_password("") is False
    assert validation.password_error("") == MSG_PASSWORD_EMPTY


def test_vr_p2_password_max_128(validation):
    assert validation.is_valid_password("a" * 124 + " b c") is True
    assert validation.is_valid_password("a" * 125 + " b c") is False


def test_vr_p3_password_needs_three_words(validation):
    assert validation.is_valid_password("green apple") is False
    assert validation.is_valid_password("green apple house") is True


def test_vr_p4_tabs_are_not_spaces(validation):
    assert validation.is_valid_password("green\tapple house") is False


def test_vr_p_password_is_not_trimmed_or_changed(validation):
    # " green apple " has 2 spaces but only 2 words; trimming would not make it valid,
    # and adding spaces around a valid one keeps it valid
    assert validation.is_valid_password("  green apple house  ") is True
    assert validation.is_valid_password(" green apple ") is False
