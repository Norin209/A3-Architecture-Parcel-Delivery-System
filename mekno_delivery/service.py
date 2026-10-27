"""Authorised use cases and Norin's persistent, idempotent delivery gateway."""
import json
from dataclasses import asdict, replace
from norin_delivery.models import DomainError, Role, new_id, now_text, required
from tola_payment import Payment
from .models import Delivery, DeliveryStaff, AvailabilitySchedule, StaffAllocation, period
from .storage import DeliveryRepository


class MeknoGateway:
    def __init__(self, repository):
        self.repository = repository

    def validate_staff(self, staff_id):
        with self.repository.transaction() as db:
            staff = self.repository.get(db, 'staff', staff_id)
            if not staff.active:
                raise DomainError('Delivery staff record is inactive.')
            return staff

    def create_or_get_delivery(self, data):
        terms = asdict(data)
        terms['amount'] = str(data.amount)
        terms['estimated_pickup'] = data.estimated_pickup.isoformat()
        terms['estimated_delivery'] = data.estimated_delivery.isoformat()
        terms['parcels'] = [list(p) for p in data.parcels]
        for name in ('quote_id', 'request_id', 'customer_id', 'pickup_address',
                     'destination_address', 'decision_recorded_by', 'decision_at'):
            required(terms[name], name)
        period(terms['estimated_pickup'], terms['estimated_delivery'])
        from norin_delivery.models import money
        money(data.amount)
        if not data.parcels or any(not p[0].strip() or not p[1].strip() for p in data.parcels):
            raise DomainError('Delivery requires described parcels.')
        with self.repository.transaction() as db:
            for delivery in self.repository.all(db, 'deliveries'):
                if delivery.terms['quote_id'] == data.quote_id:
                    stable = lambda t: {k: v for k, v in t.items() if k not in ('decision_at', 'decision_recorded_by')}
                    if stable(delivery.terms) != stable(terms):
                        raise DomainError('This quote already has different accepted delivery terms.')
                    return delivery.delivery_id
            delivery = Delivery(new_id('DEL'), terms)
            self.repository.save(db, 'deliveries', delivery)
            DeliveryOperations.event(db, delivery.delivery_id, 'Created', data.decision_recorded_by)
            return delivery.delivery_id


class DeliveryOperations:
    def __init__(self, repository, app):
        self.repository, self.app = repository, app

    @staticmethod
    def event(db, delivery_id, action, actor, note=''):
        db.execute('INSERT INTO events(payload) VALUES (?)', (json.dumps({
            'delivery_id': delivery_id, 'action': action, 'actor': actor,
            'at': now_text(), 'note': note}),))

    def office(self):
        actor = self.app.actor
        actor.require_office()
        return actor

    def manager(self):
        actor = self.office()
        if actor.role != Role.MANAGER:
            raise DomainError('Only a manager can manage delivery staff.')
        return actor

    def staff_access(self, staff_id):
        actor = self.app.actor
        if actor.role == Role.DELIVERY and actor.staff_id == staff_id:
            return actor
        return self.office()

    def create_staff(self, name, phone):
        self.manager()
        # Reuse existing phone validation without adding a fifth domain class.
        from norin_delivery.models import Customer
        Customer('validation', name, phone)
        staff = DeliveryStaff(new_id('STF'), name.strip(), phone.strip())
        with self.repository.transaction() as db:
            self.repository.save(db, 'staff', staff)
            self.repository.save(db, 'schedules', AvailabilitySchedule(staff.staff_id))
        return staff

    def validate_staff(self, staff_id):
        with self.repository.transaction() as db:
            staff = self.repository.get(db, 'staff', staff_id)
            if not staff.active:
                raise DomainError('Delivery staff record is inactive.')
        return staff

    def confirmed(self, delivery):
        # A failed Norin JSON save may leave a delivery awaiting acceptance retry.
        # Do not expose that record as an actionable accepted job yet.
        quote = self.app.repository.records.quotes.get(delivery.terms['quote_id'])
        return (quote is not None and quote.decision.value == 'Accepted'
                and quote.delivery_id == delivery.delivery_id)

    def job(self, db, delivery_id):
        delivery = self.repository.get(db, 'deliveries', delivery_id)
        if not self.confirmed(delivery):
            raise DomainError('Retry quote acceptance before operating on this delivery.')
        return delivery

    def _release(self, db, allocation, actor, reason):
        self.repository.save(db, 'allocations', replace(
            allocation, ended_at=now_text(), end_reason=reason))
        delivery = self.repository.get(db, 'deliveries', allocation.delivery_id)
        self.repository.save(db, 'deliveries', replace(
            delivery, current_allocation_id=None, state='Awaiting allocation'))
        self.event(db, delivery.delivery_id, 'Allocation released', actor.account_id, reason)

    def set_availability(self, staff_id, periods):
        actor = self.staff_access(staff_id)
        schedule = AvailabilitySchedule(staff_id, tuple(tuple(x) for x in periods))
        with self.repository.transaction() as db:
            self.repository.get(db, 'staff', staff_id)
            affected = [a for a in self.repository.all(db, 'allocations')
                        if a.current and a.staff_id == staff_id and not schedule.covers(a.start, a.end)]
            # Validate everything first: in-transit jobs cannot lose their assignment.
            for a in affected:
                self.repository.get(db, 'deliveries', a.delivery_id).require_before_pickup()
            self.repository.save(db, 'schedules', schedule)
            for a in affected:
                self._release(db, a, actor, 'Staff availability changed')
        return schedule

    def set_active(self, staff_id, active):
        actor = self.manager()
        if not isinstance(active, bool):
            raise DomainError('Choose active or inactive.')
        with self.repository.transaction() as db:
            staff = self.repository.get(db, 'staff', staff_id)
            affected = [a for a in self.repository.all(db, 'allocations')
                        if a.current and a.staff_id == staff_id] if not active else []
            for a in affected:
                self.repository.get(db, 'deliveries', a.delivery_id).require_before_pickup()
            self.repository.save(db, 'staff', replace(staff, active=active))
            for a in affected:
                self._release(db, a, actor, 'Staff deactivated')

    def _eligible(self, db, delivery, staff_id):
        staff = self.repository.get(db, 'staff', staff_id)
        start, end = delivery.terms['estimated_pickup'], delivery.terms['estimated_delivery']
        schedule = self.repository.get(db, 'schedules', staff_id)
        if not staff.eligible(schedule, start, end):
            return False
        return not any(a.staff_id == staff_id and a.delivery_id != delivery.delivery_id
                       and a.conflicts(start, end)
                       for a in self.repository.all(db, 'allocations'))

    def candidates(self, delivery_id):
        self.office()
        with self.repository.transaction() as db:
            delivery = self.job(db, delivery_id)
            delivery.require_before_pickup()
            return [s for s in self.repository.all(db, 'staff') if self._eligible(db, delivery, s.staff_id)]

    def allocate(self, delivery_id, staff_id, reason=''):
        actor = self.office()
        with self.repository.transaction() as db:
            delivery = self.job(db, delivery_id)
            delivery.require_before_pickup()
            if not self._eligible(db, delivery, staff_id):
                raise DomainError('Staff must be active, available for the whole job, and free of conflicting jobs.')
            if delivery.current_allocation_id:
                old = self.repository.get(db, 'allocations', delivery.current_allocation_id)
                if old.staff_id == staff_id:
                    return old
                self._release(db, old, actor, required(reason, 'Reassignment reason'))
            allocation = StaffAllocation(new_id('ALC'), delivery_id, staff_id,
                delivery.terms['estimated_pickup'], delivery.terms['estimated_delivery'],
                actor.account_id, now_text())
            self.repository.save(db, 'allocations', allocation)
            self.repository.save(db, 'deliveries', replace(delivery,
                state='Allocated', current_allocation_id=allocation.allocation_id))
            self.event(db, delivery_id, 'Allocated', actor.account_id, staff_id)
        return allocation

    def release(self, delivery_id, reason):
        actor = self.office()
        with self.repository.transaction() as db:
            delivery = self.job(db, delivery_id)
            delivery.require_before_pickup()
            if not delivery.current_allocation_id:
                raise DomainError('Delivery has no current allocation.')
            self._release(db, self.repository.get(db, 'allocations', delivery.current_allocation_id),
                          actor, required(reason, 'Release reason'))

    def _operator(self, db, delivery):
        if not delivery.current_allocation_id:
            raise DomainError('Allocate delivery staff first.')
        allocation = self.repository.get(db, 'allocations', delivery.current_allocation_id)
        self.validate_operator_staff(db, allocation.staff_id)
        return self.staff_access(allocation.staff_id)

    def validate_operator_staff(self, db, staff_id):
        if not self.repository.get(db, 'staff', staff_id).active:
            raise DomainError('Assigned delivery staff is inactive.')

    def pickup(self, delivery_id):
        with self.repository.transaction() as db:
            delivery = self.job(db, delivery_id)
            actor = self._operator(db, delivery)
            if delivery.state != 'Allocated':
                raise DomainError('Only an allocated delivery can be picked up.')
            self.repository.save(db, 'deliveries', replace(delivery, state='In transit', picked_up_at=now_text()))
            self.event(db, delivery_id, 'Picked up', actor.account_id)

    def collect_payment(self, delivery_id, amount):
        with self.repository.transaction() as db:
            delivery = self.job(db, delivery_id)
            actor = self._operator(db, delivery)
            if delivery.state != 'In transit' or delivery.payment_id:
                raise DomainError('Record one payment after pickup and before completion.')
            quote = self.app.repository.records.quotes.get(delivery.terms['quote_id'])
            if quote is None:
                raise DomainError('Accepted quote is not available in this workspace.')
            payment = Payment.record_collection(delivery_id, quote, amount)
            if payment.amount_received != payment.accepted_amount:
                raise DomainError('Payment must match the accepted quote amount.')
            payload = asdict(payment)
            payload.update(amount_received=str(payment.amount_received), accepted_amount=str(payment.accepted_amount),
                           collected_at=payment.collected_at.isoformat())
            db.execute('INSERT INTO payments VALUES (?, ?)', (payment.payment_id, json.dumps(payload)))
            self.repository.save(db, 'deliveries', replace(delivery, payment_id=payment.payment_id))
            self.event(db, delivery_id, 'Payment recorded', actor.account_id)
        return payment

    def complete(self, delivery_id):
        with self.repository.transaction() as db:
            delivery = self.job(db, delivery_id)
            actor = self._operator(db, delivery)
            if delivery.state != 'In transit' or not delivery.payment_id:
                raise DomainError('Pick up the parcels and record the agreed payment before completion.')
            allocation = self.repository.get(db, 'allocations', delivery.current_allocation_id)
            self.repository.save(db, 'allocations', replace(allocation, ended_at=now_text(), end_reason='Completed'))
            self.repository.save(db, 'deliveries', replace(delivery, state='Completed',
                current_allocation_id=None, completed_at=now_text()))
            self.event(db, delivery_id, 'Completed', actor.account_id)

    def view(self):
        actor = self.app.actor
        with self.repository.transaction() as db:
            deliveries = [d for d in self.repository.all(db, 'deliveries') if self.confirmed(d)]
            allocations = self.repository.all(db, 'allocations')
            if actor.role == Role.CUSTOMER:
                deliveries = [d for d in deliveries if d.terms['customer_id'] == actor.customer_id]
            elif actor.role == Role.DELIVERY:
                own_ids = {a.delivery_id for a in allocations if a.staff_id == actor.staff_id}
                deliveries = [d for d in deliveries if d.delivery_id in own_ids]
            ids = {d.delivery_id for d in deliveries}
            visible = [a for a in allocations if a.delivery_id in ids]
            if actor.role == Role.DELIVERY:
                visible = [a for a in visible if a.staff_id == actor.staff_id]
            if actor.role == Role.CUSTOMER:
                visible = []
            staff = self.repository.all(db, 'staff') if actor.role != Role.CUSTOMER else []
            if actor.role == Role.DELIVERY:
                staff = [s for s in staff if s.staff_id == actor.staff_id]
            staff_ids = {s.staff_id for s in staff}
            events = [json.loads(x[0]) for x in db.execute('SELECT payload FROM events ORDER BY id')]
            return {'deliveries': [asdict(d) for d in deliveries],
                    'delivery_staff': [asdict(s) for s in staff],
                    'schedules': [asdict(s) for s in self.repository.all(db, 'schedules') if s.staff_id in staff_ids],
                    'allocations': [dict(asdict(a), current=a.current) for a in visible],
                    'delivery_events': [e for e in events if e['delivery_id'] in ids]
                        if actor.role in (Role.MANAGER, Role.OFFICE) else [],
                    'payments': [p for (raw,) in db.execute('SELECT payload FROM payments')
                                 if (p := json.loads(raw))['delivery_id'] in ids]}
