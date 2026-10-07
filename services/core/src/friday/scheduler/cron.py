"""Deterministic cron and calendar adaptation for Friday Scheduler (Phase 11).

Invariants:
1. 5-field cron validation only (no seconds, macros like @daily, years, or hash extensions).
2. IANA timezone validation with zoneinfo (default America/New_York).
3. Monotonic watermark progression prevents clock-rollback replay.
4. Admission grace window of 60 seconds; overdue runs skip forward to future occurrence with zero backlog replay.
5. Search window bounded to 8 years to prevent unbounded evaluation loops.
6. DST transitions: nonexistent local time advances to valid instant, repeated ambiguous time runs once on earlier occurrence.
"""

from datetime import datetime
import time
from typing import Optional, Tuple
import zoneinfo
import croniter

from friday.scheduler.models import InvalidScheduleError, ScheduleType


class CronCalendarAdapter:
    DEFAULT_TIMEZONE = "America/New_York"
    ADMISSION_GRACE_SECONDS = 60
    MAX_SEARCH_WINDOW_SECONDS = 8 * 366 * 86400  # ~8 years
    MIN_DELAY_SECONDS = 60
    MAX_DELAY_SECONDS = 8 * 366 * 86400

    @classmethod
    def validate_timezone(cls, tz_name: str) -> zoneinfo.ZoneInfo:
        """Validate and resolve an IANA timezone string."""
        if not tz_name or not isinstance(tz_name, str):
            raise InvalidScheduleError("Timezone must be a non-empty string.")
        try:
            return zoneinfo.ZoneInfo(tz_name.strip())
        except Exception as exc:
            raise InvalidScheduleError(f"Invalid IANA timezone '{tz_name}': {exc}") from exc

    @classmethod
    def validate_cron_expression(cls, expression: str) -> None:
        """Validate standard 5-field cron expression, strictly forbidding macros and extensions."""
        if not expression or not isinstance(expression, str):
            raise InvalidScheduleError("Cron expression must be a non-empty string.")

        expr = expression.strip()
        parts = expr.split()
        # Forbid macros (@daily, @hourly, @reboot, etc.)
        if expr.startswith("@") or any(p.startswith("@") for p in parts):
            raise InvalidScheduleError(f"Cron macros are not permitted: '{expression}'")

        if len(parts) != 5:
            raise InvalidScheduleError(
                f"Cron expression must contain exactly 5 whitespace-separated fields (minute, hour, dom, month, dow). "
                f"Got {len(parts)} fields: '{expression}'"
            )

        # Forbid non-standard extensions (seconds/years syntax, hash extensions H/15, '?', 'L', 'W', '#')
        for p in parts:
            for forbidden_char in ("H", "h", "?", "L", "l", "W", "w", "#"):
                if forbidden_char in p:
                    raise InvalidScheduleError(
                        f"Non-standard cron extension character '{forbidden_char}' is not permitted: '{expression}'"
                    )

        if not croniter.croniter.is_valid(expr):
            raise InvalidScheduleError(f"Invalid cron syntax: '{expression}'")

        # Test evaluation with bounded window to verify the schedule matches at least one real date
        tz = zoneinfo.ZoneInfo("UTC")
        now_dt = datetime.now(tz)
        try:
            c = croniter.croniter(expr, now_dt)
            next_dt = c.get_next(datetime)
            if (next_dt.timestamp() - now_dt.timestamp()) > cls.MAX_SEARCH_WINDOW_SECONDS:
                raise InvalidScheduleError(
                    f"Cron expression '{expression}' matches no valid date within the 8-year search window."
                )
        except croniter.CroniterBadDateError as exc:
            raise InvalidScheduleError(f"Cron expression '{expression}' produces no valid calendar dates: {exc}") from exc
        except Exception as exc:
            if isinstance(exc, InvalidScheduleError):
                raise
            raise InvalidScheduleError(f"Cron expression '{expression}' evaluation failed: {exc}") from exc

    @classmethod
    def validate_delay(cls, delay_seconds: int) -> None:
        """Validate delay in seconds for one-shot jobs."""
        if not isinstance(delay_seconds, int):
            raise InvalidScheduleError(f"Delay seconds must be an integer, got {type(delay_seconds).__name__}.")
        if delay_seconds < cls.MIN_DELAY_SECONDS:
            raise InvalidScheduleError(
                f"One-shot delay must be at least {cls.MIN_DELAY_SECONDS} seconds. Got {delay_seconds}."
            )
        if delay_seconds > cls.MAX_DELAY_SECONDS:
            raise InvalidScheduleError(
                f"One-shot delay exceeds maximum allowed window of {cls.MAX_DELAY_SECONDS} seconds."
            )

    @classmethod
    def get_next_occurrence(
        cls,
        expression: str,
        tz_name: str,
        base_time_utc: int,
    ) -> int:
        """Compute the next integer UTC timestamp for a cron expression after base_time_utc.
        
        Handles DST spring forward and repeated fall back unambiguously.
        """
        cls.validate_cron_expression(expression)
        tz = cls.validate_timezone(tz_name)

        base_dt = datetime.fromtimestamp(base_time_utc, tz=tz)
        try:
            c = croniter.croniter(expression.strip(), base_dt)
            next_dt = c.get_next(datetime)

            # Check for ambiguous repeated local time on DST fall back.
            # If next_dt has fold == 1 and matches the identical local wall-clock time as base_dt,
            # the earlier occurrence (fold == 0) has already run, so we advance past fold 1.
            if getattr(next_dt, "fold", 0) == 1:
                if (
                    next_dt.year == base_dt.year
                    and next_dt.month == base_dt.month
                    and next_dt.day == base_dt.day
                    and next_dt.hour == base_dt.hour
                    and next_dt.minute == base_dt.minute
                ):
                    next_dt = c.get_next(datetime)

            delta_sec = next_dt.timestamp() - base_time_utc
            if delta_sec > cls.MAX_SEARCH_WINDOW_SECONDS:
                raise InvalidScheduleError(
                    f"Cron expression '{expression}' matches no valid date within 8 years of base time {base_time_utc}."
                )

            next_ts = int(next_dt.timestamp())
            if next_ts <= base_time_utc:
                raise InvalidScheduleError(
                    f"Cron calculation yielded non-monotonic timestamp {next_ts} <= base {base_time_utc}."
                )

            return next_ts
        except croniter.CroniterBadDateError as exc:
            raise InvalidScheduleError(f"Failed to find next date for '{expression}': {exc}") from exc
        except Exception as exc:
            if isinstance(exc, InvalidScheduleError):
                raise
            raise InvalidScheduleError(f"Error evaluating cron expression '{expression}': {exc}") from exc

    @classmethod
    def evaluate_admission(
        cls,
        scheduled_for_utc: int,
        now_utc: int,
        grace_seconds: int = ADMISSION_GRACE_SECONDS,
    ) -> Tuple[bool, str]:
        """Evaluate whether a scheduled occurrence is admissible right now.
        
        Returns:
            (is_admissible, reason)
            - (False, "not_due"): Occurrence is in the future.
            - (True, "admitted"): Within the [scheduled_for_utc, scheduled_for_utc + grace_seconds] window.
            - (False, "overdue_skipped"): Missed the grace window (> scheduled_for_utc + grace_seconds).
        """
        if now_utc < scheduled_for_utc:
            return False, "not_due"
        if now_utc <= scheduled_for_utc + grace_seconds:
            return True, "admitted"
        return False, "overdue_skipped"

    @classmethod
    def compute_next_run(
        cls,
        schedule_type: ScheduleType,
        cron_expression: Optional[str] = None,
        delay_seconds: Optional[int] = None,
        tz_name: str = DEFAULT_TIMEZONE,
        base_time_utc: Optional[int] = None,
        watermark_utc: Optional[int] = None,
    ) -> Optional[int]:
        """Compute the next scheduled run timestamp in UTC enforcing monotonicity."""
        current_time = int(time.time()) if base_time_utc is None else base_time_utc
        effective_base = max(current_time, watermark_utc or 0)

        if schedule_type == ScheduleType.ONCE:
            if delay_seconds is None:
                raise InvalidScheduleError("delay_seconds is required for one-shot schedules.")
            cls.validate_delay(delay_seconds)
            return effective_base + delay_seconds

        elif schedule_type == ScheduleType.CRON:
            if not cron_expression:
                raise InvalidScheduleError("cron_expression is required for cron schedules.")
            return cls.get_next_occurrence(cron_expression, tz_name, effective_base)

        else:
            raise InvalidScheduleError(f"Unsupported schedule type: {schedule_type}")
