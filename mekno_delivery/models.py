"""Four business classes retained from the group's A2 model.

Scheduling uses Melbourne wall times, matching Norin's accepted estimates.
Intervals are half open: a job ending at 11:00 can precede one starting at 11:00.
"""
from dataclasses import dataclass
from datetime import datetime
from norin_delivery.models import DomainError, required


def period(start: str, end: str) -> tuple[datetime, datetime]:
    try:
        first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
        if first.tzinfo is not None or last.tzinfo is not None or last <= first:
            raise ValueError
        return first, last
    except (ValueError, TypeError) as exc:
        raise DomainError('Use Melbourne local times, with end later than start.') from exc


@dataclass(frozen=True)
class AvailabilitySchedule:
    staff_id: str
    periods: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        required(self.staff_id, 'Staff ID')
        canonical = tuple((period(a, b)[0].isoformat(), period(a, b)[1].isoformat())
                          for a, b in self.periods)
        object.__setattr__(self, 'periods', canonical)
        ordered = sorted(canonical)
        previous = None
        for start, end in ordered:
            first, last = period(start, end)
            if previous is not None and first < previous:
                raise DomainError('Availability periods must not overlap.')
            previous = last

    def covers(self, start: str, end: str) -> bool:
        first, last = period(start, end)
        # Adjacent shifts can jointly cover one job.
        cursor = first
        for a, b in sorted(self.periods):
            left, right = period(a, b)
            if left <= cursor < right:
                cursor = right
            if cursor >= last:
                return True
        return False


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

    def eligible(self, schedule: AvailabilitySchedule, start: str, end: str) -> bool:
        return self.active and schedule.staff_id == self.staff_id and schedule.covers(start, end)


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

    def __post_init__(self):
        period(self.start, self.end)

    @property
    def current(self) -> bool:
        return self.ended_at is None

    def conflicts(self, start: str, end: str) -> bool:
        first, last = period(start, end)
        own_start, own_end = period(self.start, self.end)
        return self.current and first < own_end and own_start < last


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
