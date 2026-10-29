"""Four business classes retained from the group's A2 model.

Scheduling uses repeating Melbourne wall-clock shifts, matching Norin's
accepted estimates when checking a particular delivery date.
Intervals are half open: a job ending at 11:00 can precede one starting at 11:00.
"""
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from norin_delivery.models import DomainError, required

WEEKDAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
            'Saturday', 'Sunday')
WEEK_MINUTES = 7 * 24 * 60


def period(start: str, end: str) -> tuple[datetime, datetime]:
    try:
        first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
        if first.tzinfo is not None or last.tzinfo is not None or last <= first:
            raise ValueError
        return first, last
    except (ValueError, TypeError) as exc:
        raise DomainError('Use Melbourne local times, with end later than start.') from exc


def weekly_shift(day: str, clock_in: str, clock_out: str):
    if not isinstance(day, str) or day not in WEEKDAYS:
        raise DomainError('Choose a weekday from Monday to Sunday.')
    if (not isinstance(clock_in, str) or not isinstance(clock_out, str)
            or not re.fullmatch(r'\d{2}:\d{2}', clock_in)
            or not re.fullmatch(r'\d{2}:\d{2}', clock_out)):
        raise DomainError('Use HH:MM for clock-in and clock-out times.')
    try:
        start_time = datetime.strptime(clock_in, '%H:%M')
        end_time = datetime.strptime(clock_out, '%H:%M')
    except ValueError as exc:
        raise DomainError('Enter valid clock-in and clock-out times.') from exc
    start = WEEKDAYS.index(day) * 1440 + start_time.hour * 60 + start_time.minute
    end = WEEKDAYS.index(day) * 1440 + end_time.hour * 60 + end_time.minute
    if end == start:
        raise DomainError('Clock-out must differ from clock-in.')
    if end < start:
        end += 1440  # An overnight shift ends the next day.
    return start, end


@dataclass(frozen=True)
class AvailabilitySchedule:
    staff_id: str
    periods: tuple[tuple[str, str, str], ...] = ()
    legacy_periods: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        required(self.staff_id, 'Staff ID')
        raw = tuple(tuple(row) for row in self.periods)
        legacy = tuple(tuple(row) for row in self.legacy_periods)
        if raw and all(len(row) == 2 for row in raw):
            if legacy:
                raise DomainError('Cannot mix dated and weekly availability.')
            legacy, raw = raw, ()
        if any(len(row) != 3 for row in raw):
            raise DomainError('Each weekly shift needs a day, clock-in and clock-out.')
        if raw and legacy:
            raise DomainError('Cannot mix dated and weekly availability.')
        canonical = tuple(sorted(raw, key=lambda row: WEEKDAYS.index(row[0])
                                 if row[0] in WEEKDAYS else len(WEEKDAYS)))
        minutes = []
        days = set()
        for day, clock_in, clock_out in canonical:
            if day in days:
                raise DomainError('Only one working shift is allowed per weekday.')
            days.add(day)
            minutes.append(weekly_shift(day, clock_in, clock_out))
        for index, (left, right) in enumerate(minutes):
            for other_left, other_right in minutes[index + 1:]:
                for offset in (-WEEK_MINUTES, 0, WEEK_MINUTES):
                    if left < other_right + offset and other_left + offset < right:
                        raise DomainError('Weekly working shifts must not overlap.')
        canonical_legacy = tuple((period(a, b)[0].isoformat(),
                                  period(a, b)[1].isoformat()) for a, b in legacy)
        previous = None
        for start, end in sorted(canonical_legacy):
            first, last = period(start, end)
            if previous is not None and first < previous:
                raise DomainError('Availability periods must not overlap.')
            previous = last
        object.__setattr__(self, 'periods', canonical)
        object.__setattr__(self, 'legacy_periods', canonical_legacy)

    def covers(self, start: str, end: str) -> bool:
        first, last = period(start, end)
        windows = self._windows(first, last)
        # Adjacent shifts can jointly cover one job across a day boundary.
        cursor = first
        for left, right in sorted(windows):
            if left <= cursor < right:
                cursor = right
            if cursor >= last:
                return True
        return False

    def available_at(self, when: str, *, delivery: bool = False) -> bool:
        try:
            moment = datetime.fromisoformat(when)
            if moment.tzinfo is not None:
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise DomainError('Use a Melbourne local pickup or delivery time.') from exc
        windows = self._windows(moment, moment + timedelta(minutes=1))
        # A delivery can finish exactly at clock-out; pickup needs time to start.
        return any(left <= moment <= right if delivery else left <= moment < right
                   for left, right in windows)

    def _windows(self, first: datetime, last: datetime):
        if self.legacy_periods:
            windows = [period(a, b) for a, b in self.legacy_periods]
        else:
            monday = datetime.combine(first.date() - timedelta(days=first.weekday()),
                                      time.min)
            week_count = (last - monday).days // 7 + 2
            windows = []
            for week in range(-1, week_count + 1):
                for day, clock_in, clock_out in self.periods:
                    left, right = weekly_shift(day, clock_in, clock_out)
                    windows.append((monday + timedelta(minutes=left + week * WEEK_MINUTES),
                                    monday + timedelta(minutes=right + week * WEEK_MINUTES)))
        return windows


@dataclass(frozen=True)
class DeliveryStaff:
    staff_id: str
    display_name: str
    phone: str
    active: bool = True

    def __post_init__(self):
        required(self.staff_id, 'Staff ID')
        required(self.display_name, 'Staff name')
        required(self.phone, 'Phone')

    def eligible(self, schedule: AvailabilitySchedule, when: str, *, delivery: bool = False) -> bool:
        return self.active and schedule.staff_id == self.staff_id and schedule.available_at(when, delivery=delivery)


@dataclass(frozen=True)
class StaffAllocation:
    allocation_id: str
    delivery_id: str
    staff_id: str
    start: str
    end: str
    assigned_by: str
    assigned_at: str
    ended_at: str | None = None
    end_reason: str = ''
    phase: str = 'Whole job'  # Existing records retain their original meaning.

    def __post_init__(self):
        period(self.start, self.end)
        if self.phase not in ('Whole job', 'Pickup', 'Delivery'):
            raise DomainError('Choose a valid allocation phase.')

    @property
    def current(self) -> bool:
        return self.ended_at is None

    def conflicts(self, start: str, end: str) -> bool:
        first, last = period(start, end)
        own_start, own_end = period(self.start, self.end)
        return self.current and first < own_end and own_start < last

    def conflicts_at(self, when: str) -> bool:
        moment = datetime.fromisoformat(when)
        own_start, own_end = period(self.start, self.end)
        return self.current and own_start <= moment < own_end


@dataclass(frozen=True)
class Delivery:
    delivery_id: str
    terms: dict
    state: str = 'Awaiting allocation'
    current_allocation_id: str | None = None
    picked_up_at: str | None = None
    completed_at: str | None = None
    payment_id: str | None = None

    def require_before_pickup(self):
        if self.state not in ('Awaiting allocation', 'Allocated'):
            raise DomainError('Allocation can change only before pickup.')
