"""FR-16, FR-18 to FR-20, FR-23 to FR-25, NFR-19: failed-attempt counter and 5-second lock.

Uses a fake clock, so no test waits in real time.
"""

import importlib

import pytest

EMAIL = "user@example.com"


@pytest.fixture
def lockout():
    return importlib.import_module("backend.lockout")


@pytest.fixture
def tracker(lockout, fake_clock):
    return lockout.LoginAttemptTracker(max_failures=3, lockout_seconds=5, clock=fake_clock)


def _lock(tracker):
    for _ in range(3):
        tracker.record_failure(EMAIL)


def test_nfr19_named_constants(lockout):
    assert lockout.MAX_FAILED_ATTEMPTS == 3
    assert lockout.LOCK_SECONDS == 5


def test_nfr19_defaults_use_the_constants(lockout, fake_clock):
    tracker = lockout.LoginAttemptTracker(clock=fake_clock)
    assert [tracker.record_failure(EMAIL) for _ in range(3)] == [2, 1, 0]
    assert tracker.retry_after(EMAIL) == 5


def test_new_email_has_no_failures_and_no_lock(tracker):
    assert tracker.failures(EMAIL) == 0
    assert tracker.retry_after(EMAIL) == 0


def test_fr18_each_failure_increases_count(tracker):
    tracker.record_failure(EMAIL)
    assert tracker.failures(EMAIL) == 1
    tracker.record_failure(EMAIL)
    assert tracker.failures(EMAIL) == 2


def test_fr16_failures_return_attempts_remaining(tracker):
    assert tracker.record_failure(EMAIL) == 2
    assert tracker.record_failure(EMAIL) == 1


def test_fr19_third_failure_starts_five_second_lock(tracker):
    tracker.record_failure(EMAIL)
    tracker.record_failure(EMAIL)
    assert tracker.retry_after(EMAIL) == 0
    assert tracker.record_failure(EMAIL) == 0
    assert tracker.retry_after(EMAIL) == 5


@pytest.mark.parametrize(
    "elapsed, expected",
    [(0, 5), (0.5, 5), (1.0, 4), (2.2, 3), (4.0, 1), (4.999, 1)],
)
def test_fr20_retry_after_is_remaining_seconds_rounded_up(tracker, fake_clock, elapsed, expected):
    _lock(tracker)
    fake_clock.advance(elapsed)
    assert tracker.retry_after(EMAIL) == expected


def test_fr20_lock_ends_after_exactly_five_seconds(tracker, fake_clock):
    _lock(tracker)
    fake_clock.advance(5)
    assert tracker.retry_after(EMAIL) == 0


def test_fr20_checking_lock_does_not_extend_it(tracker, fake_clock):
    _lock(tracker)
    fake_clock.advance(3)
    assert tracker.retry_after(EMAIL) == 2
    assert tracker.retry_after(EMAIL) == 2
    fake_clock.advance(2)
    assert tracker.retry_after(EMAIL) == 0


def test_fr23_count_resets_when_lock_expires(tracker, fake_clock):
    _lock(tracker)
    fake_clock.advance(5)
    assert tracker.failures(EMAIL) == 0


def test_fr23_fresh_three_attempts_after_lock(tracker, fake_clock):
    _lock(tracker)
    fake_clock.advance(6)
    # no retry_after() call first: the reset must not depend on it
    assert tracker.record_failure(EMAIL) == 2
    assert tracker.record_failure(EMAIL) == 1
    assert tracker.record_failure(EMAIL) == 0
    assert tracker.retry_after(EMAIL) == 5


def test_fr23_reset_without_any_call_during_lock(tracker, fake_clock):
    _lock(tracker)
    fake_clock.advance(100)
    assert tracker.failures(EMAIL) == 0
    assert tracker.retry_after(EMAIL) == 0


def test_fr24_success_resets_count(tracker):
    tracker.record_failure(EMAIL)
    tracker.record_failure(EMAIL)
    tracker.record_success(EMAIL)
    assert tracker.failures(EMAIL) == 0
    assert tracker.record_failure(EMAIL) == 2


def test_fr25_failures_do_not_expire_on_their_own(tracker, fake_clock):
    tracker.record_failure(EMAIL)
    tracker.record_failure(EMAIL)
    fake_clock.advance(3600)
    assert tracker.failures(EMAIL) == 2
    assert tracker.record_failure(EMAIL) == 0
    assert tracker.retry_after(EMAIL) == 5


def test_fr18_counts_are_kept_per_email(tracker):
    _lock(tracker)
    other = "other@example.com"
    assert tracker.failures(other) == 0
    assert tracker.retry_after(other) == 0
    assert tracker.record_failure(other) == 2
    assert tracker.retry_after(EMAIL) == 5
