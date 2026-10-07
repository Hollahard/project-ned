"""Tests for CronCalendarAdapter in Friday Scheduler (Phase 11 Milestone 3).

Verifies:
1. Strict 5-field cron validation (rejection of seconds, years, macros, and non-standard extensions).
2. IANA timezone validation with zoneinfo.
3. One-shot delay constraints (>= 60s).
4. DST transition handling (spring forward and fall back ambiguous resolution).
5. Monotonic progression and clock rollback resistance via watermark.
6. 60-second admission grace evaluation and overdue skipping with zero backlog replay.
"""

from datetime import datetime
import pytest
import zoneinfo

from friday.scheduler.cron import CronCalendarAdapter
from friday.scheduler.models import InvalidScheduleError, ScheduleType


def test_cron_validation_valid_expressions():
    """Valid standard 5-field expressions pass validation."""
    valid_expressions = [
        "* * * * *",
        "*/5 * * * *",
        "0 9 * * 1-5",
        "30 2 1 * *",
        "0 0 1 1 *",
        "15,45 10-18 * * 1,3,5",
    ]
    for expr in valid_expressions:
        CronCalendarAdapter.validate_cron_expression(expr)


def test_cron_validation_rejects_non_5_fields():
    """Expressions with fewer or more than 5 fields are rejected."""
    invalid_counts = [
        "* * * *",             # 4 fields
        "0 */5 * * * *",       # 6 fields (seconds)
        "* * * * * *",         # 6 fields
        "* * * * * 2026",      # 6 fields (years)
        "* * *",               # 3 fields
        "",                    # empty
    ]
    for expr in invalid_counts:
        with pytest.raises(InvalidScheduleError, match="Cron expression must contain exactly 5 whitespace-separated fields|non-empty"):
            CronCalendarAdapter.validate_cron_expression(expr)


def test_cron_validation_rejects_macros():
    """Cron macros (@daily, @hourly, etc.) are strictly forbidden."""
    macros = ["@daily", "@hourly", "@reboot", "@weekly", "@monthly", "@yearly"]
    for macro in macros:
        with pytest.raises(InvalidScheduleError, match="Cron macros are not permitted"):
            CronCalendarAdapter.validate_cron_expression(macro)


def test_cron_validation_rejects_extensions():
    """Non-standard extensions (hash syntax, ?, L, W) are rejected."""
    extensions = [
        "H/15 * * * *",
        "? * * * *",
        "0 0 ? * 1",
        "0 0 L * *",
        "0 0 1W * *",
        "0 0 * * 1#2",
    ]
    for expr in extensions:
        with pytest.raises(InvalidScheduleError, match="Non-standard cron extension character"):
            CronCalendarAdapter.validate_cron_expression(expr)


def test_cron_validation_rejects_impossible_dates():
    """Expressions that never match (e.g., Feb 30) are rejected."""
    impossible = "0 0 30 2 *"
    with pytest.raises(InvalidScheduleError, match="produces no valid calendar dates|evaluation failed"):
        CronCalendarAdapter.validate_cron_expression(impossible)


def test_timezone_validation():
    """Validates IANA timezones and rejects invalid or malformed strings."""
    tz = CronCalendarAdapter.validate_timezone("America/New_York")
    assert tz.key == "America/New_York"

    tz_utc = CronCalendarAdapter.validate_timezone("UTC")
    assert tz_utc.key == "UTC"

    with pytest.raises(InvalidScheduleError, match="Invalid IANA timezone"):
        CronCalendarAdapter.validate_timezone("Invalid/Nowhere")

    with pytest.raises(InvalidScheduleError, match="Timezone must be a non-empty string"):
        CronCalendarAdapter.validate_timezone("")


def test_delay_validation():
    """One-shot delay must be an integer >= 60 seconds."""
    CronCalendarAdapter.validate_delay(60)
    CronCalendarAdapter.validate_delay(3600)

    with pytest.raises(InvalidScheduleError, match="at least 60 seconds"):
        CronCalendarAdapter.validate_delay(59)

    with pytest.raises(InvalidScheduleError, match="at least 60 seconds"):
        CronCalendarAdapter.validate_delay(0)

    with pytest.raises(InvalidScheduleError, match="at least 60 seconds"):
        CronCalendarAdapter.validate_delay(-10)


def test_dst_spring_forward():
    """Spring forward skips nonexistent local time and advances cleanly to next valid instant."""
    # In America/New_York on March 8, 2026, 02:00 skips to 03:00.
    # Schedule for 02:30 AM should advance cleanly without crash.
    tz = zoneinfo.ZoneInfo("America/New_York")
    base_dt = datetime(2026, 3, 8, 1, 0, tzinfo=tz)
    base_utc = int(base_dt.timestamp())

    next_utc = CronCalendarAdapter.get_next_occurrence("30 2 * * *", "America/New_York", base_utc)
    next_dt = datetime.fromtimestamp(next_utc, tz=tz)

    assert next_dt.year == 2026
    assert next_dt.month == 3
    assert next_dt.day == 8
    assert next_utc > base_utc


def test_dst_fall_back_single_execution():
    """Fall back repeated local time runs once on the earlier occurrence and advances to the next day."""
    # In America/New_York on November 1, 2026, 01:30 AM EDT (fold=0) is followed by 01:30 AM EST (fold=1).
    tz = zoneinfo.ZoneInfo("America/New_York")
    base_dt = datetime(2026, 11, 1, 1, 30, fold=0, tzinfo=tz)
    base_utc = int(base_dt.timestamp())

    next_utc = CronCalendarAdapter.get_next_occurrence("30 1 * * *", "America/New_York", base_utc)
    next_dt = datetime.fromtimestamp(next_utc, tz=tz)

    # Next run must be the next calendar day (November 2, 2026), NOT repeating on Nov 1 fold 1
    assert next_dt.year == 2026
    assert next_dt.month == 11
    assert next_dt.day == 2
    assert next_dt.hour == 1
    assert next_dt.minute == 30


def test_monotonic_watermark_and_clock_rollback():
    """Schedule computation respects watermark and prevents backward calculation if clock rolls back."""
    # Base timestamp
    t0 = 1770000000
    cron = "0 12 * * *"  # Daily noon

    next_run = CronCalendarAdapter.compute_next_run(
        schedule_type=ScheduleType.CRON,
        cron_expression=cron,
        tz_name="UTC",
        base_time_utc=t0,
        watermark_utc=None,
    )
    assert next_run is not None
    assert next_run > t0

    # Simulate clock rolling back before t0: system time is t0 - 50000
    rolled_back_time = t0 - 50000
    watermark = next_run  # We previously progressed to next_run

    subsequent_run = CronCalendarAdapter.compute_next_run(
        schedule_type=ScheduleType.CRON,
        cron_expression=cron,
        tz_name="UTC",
        base_time_utc=rolled_back_time,
        watermark_utc=watermark,
    )
    # Monotonicity invariant: subsequent_run must be strictly > watermark
    assert subsequent_run is not None
    assert subsequent_run > watermark


def test_admission_evaluation():
    """Verifies 60-second grace window admission logic."""
    scheduled_at = 1000

    # Future occurrence (not due)
    admit, reason = CronCalendarAdapter.evaluate_admission(scheduled_for_utc=scheduled_at, now_utc=999)
    assert not admit
    assert reason == "not_due"

    # Exactly on time
    admit, reason = CronCalendarAdapter.evaluate_admission(scheduled_for_utc=scheduled_at, now_utc=1000)
    assert admit
    assert reason == "admitted"

    # Within 60s grace
    admit, reason = CronCalendarAdapter.evaluate_admission(scheduled_for_utc=scheduled_at, now_utc=1060)
    assert admit
    assert reason == "admitted"

    # 1 second past grace: overdue skipped
    admit, reason = CronCalendarAdapter.evaluate_admission(scheduled_for_utc=scheduled_at, now_utc=1061)
    assert not admit
    assert reason == "overdue_skipped"
