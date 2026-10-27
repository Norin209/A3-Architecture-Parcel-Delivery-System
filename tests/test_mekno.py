"""Behavioural checks for Mekno's module and the real Norin handoff."""
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from norin_delivery.models import DomainError, Role
from norin_delivery.service import DeliveryApplication
from norin_delivery.storage import JsonRepository, StorageError
from norin_delivery.integration import AcceptedDeliveryData
from mekno_delivery import DeliveryRepository, DeliveryOperations, MeknoGateway

PASSWORD = 'DemoPass123!'


class DeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as folder:
            app = DeliveryApplication(JsonRepository(Path(folder) / 'seed.json'), None)
            app.setup_manager('manager', PASSWORD)
            cls.customer = app.register_customer('Test Customer', '0412345678', '', 'customer', PASSWORD)
            cls.seed = deepcopy(app.repository.records)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)
        self.repo = DeliveryRepository(self.path / 'delivery.sqlite3')
        self.gateway = MeknoGateway(self.repo)
        source = JsonRepository(self.path / 'records.json')
        source.commit(deepcopy(self.seed))
        self.app = DeliveryApplication(source, self.gateway)
        self.app.login('manager', PASSWORD)
        self.ops = DeliveryOperations(self.repo, self.app)
        self.one = self.ops.create_staff('Driver One', '0412345678')
        self.two = self.ops.create_staff('Driver Two', '0412345679')
        self.shift = [('2026-11-01 08:00', '2026-11-01 18:00')]
        for staff in (self.one, self.two):
            self.ops.set_availability(staff.staff_id, self.shift)

    def quote(self, start='09:00', end='11:00'):
        request = self.app.create_request(self.customer.customer_id, 'Melbourne', 'Hawthorn', ['Books', 'Clothes'])
        return self.app.create_quote(request.request_id, '45.50', '2026-11-01 '+start, '2026-11-01 '+end)

    def delivery(self, start='09:00', end='11:00'):
        return self.app.decide_quote(self.quote(start, end).quote_id, True).delivery_id

    def test_real_handoff_restart_and_conflicting_terms(self):
        quote = self.app.decide_quote(self.quote().quote_id, True)
        data = AcceptedDeliveryData.from_quote(quote, self.app.get_request(quote.request_id))
        restarted = MeknoGateway(DeliveryRepository(self.path / 'delivery.sqlite3'))
        self.assertEqual(quote.delivery_id, restarted.create_or_get_delivery(replace(data, decision_at='retry-time')))
        with self.assertRaises(DomainError):
            restarted.create_or_get_delivery(replace(data, destination_address='Elsewhere'))
        self.assertEqual(1, len(self.ops.view()['deliveries']))

    def test_retry_after_norin_save_failure(self):
        quote = self.quote()
        with patch.object(self.app.repository, 'commit', side_effect=StorageError('disk full')):
            with self.assertRaises(StorageError):
                self.app.decide_quote(quote.quote_id, True)
        self.assertEqual([], self.ops.view()['deliveries'])
        with self.repo.transaction() as db:
            orphan_id = self.repo.all(db, 'deliveries')[0].delivery_id
        with self.assertRaises(DomainError):
            self.ops.allocate(orphan_id, self.one.staff_id)
        accepted = self.app.decide_quote(quote.quote_id, True)
        self.assertEqual(orphan_id, accepted.delivery_id)

    def test_conflicts_adjacent_jobs_and_reassignment_history(self):
        first = self.delivery()
        second = self.delivery('10:00', '12:00')
        adjacent = self.delivery('11:00', '13:00')
        self.ops.allocate(first, self.one.staff_id)
        with self.assertRaises(DomainError):
            self.ops.allocate(second, self.one.staff_id)
        self.ops.allocate(adjacent, self.one.staff_id)
        with self.assertRaises(DomainError):
            self.ops.allocate(first, self.two.staff_id)
        self.ops.allocate(first, self.two.staff_id, 'Driver unavailable')
        history = [a for a in self.ops.view()['allocations'] if a['delivery_id'] == first]
        self.assertEqual(2, len(history))
        self.assertEqual(1, sum(a['current'] for a in history))
        self.assertEqual('Driver unavailable', history[0]['end_reason'])

    def test_availability_change_releases_and_no_candidate_remains_unallocated(self):
        job = self.delivery()
        self.ops.allocate(job, self.one.staff_id)
        self.ops.set_availability(self.one.staff_id, [])
        self.ops.set_active(self.two.staff_id, False)
        self.assertEqual([], self.ops.candidates(job))
        self.assertEqual('Awaiting allocation', self.ops.view()['deliveries'][0]['state'])
        self.assertFalse(self.ops.view()['allocations'][0]['current'])

    def test_invalid_availability_does_not_release_assignment(self):
        job = self.delivery()
        self.ops.allocate(job, self.one.staff_id)
        with self.assertRaises(DomainError):
            self.ops.set_availability(self.one.staff_id, self.shift + self.shift)
        self.assertEqual('Allocated', self.ops.view()['deliveries'][0]['state'])

    def test_pickup_payment_completion_and_restarting(self):
        job = self.delivery()
        self.ops.allocate(job, self.one.staff_id)
        with self.assertRaises(DomainError):
            self.ops.complete(job)
        self.ops.pickup(job)
        with self.assertRaises(DomainError):
            self.ops.set_availability(self.one.staff_id, [])
        with self.assertRaises(DomainError):
            self.ops.set_active(self.one.staff_id, False)
        with self.assertRaises(DomainError):
            self.ops.allocate(job, self.two.staff_id, 'Too late')
        with self.assertRaises(DomainError):
            self.ops.collect_payment(job, '44.00')
        self.assertEqual([], self.ops.view()['payments'])
        self.ops.collect_payment(job, '45.50')
        self.ops.complete(job)
        restarted = DeliveryOperations(DeliveryRepository(self.path / 'delivery.sqlite3'), self.app)
        view = restarted.view()
        self.assertEqual('Completed', view['deliveries'][0]['state'])
        self.assertEqual(1, len(view['payments']))
        self.assertFalse(view['allocations'][0]['current'])

    def test_customer_and_other_driver_permissions(self):
        job = self.delivery()
        self.ops.allocate(job, self.one.staff_id)
        self.app.register_staff_account('driverone', PASSWORD, Role.DELIVERY, self.one.staff_id)
        self.app.register_staff_account('drivertwo', PASSWORD, Role.DELIVERY, self.two.staff_id)
        self.app.login('drivertwo', PASSWORD)
        self.assertEqual([], self.ops.view()['deliveries'])
        with self.assertRaises(DomainError):
            self.ops.pickup(job)
        with self.assertRaises(DomainError):
            self.ops.set_availability(self.one.staff_id, [])
        self.app.login('customer', PASSWORD)
        self.assertEqual(1, len(self.ops.view()['deliveries']))
        self.assertEqual([], self.ops.view()['delivery_staff'])
        with self.assertRaises(DomainError):
            self.ops.allocate(job, self.two.staff_id)
        self.app.login('driverone', PASSWORD)
        self.ops.pickup(job)

    def test_sql_transaction_rolls_back_reassignment_failure(self):
        job = self.delivery()
        self.ops.allocate(job, self.one.staff_id)
        original = self.repo.save
        def fail(db, table, record):
            if table == 'allocations' and record.staff_id == self.two.staff_id:
                raise StorageError('disk full')
            original(db, table, record)
        with patch.object(self.repo, 'save', side_effect=fail):
            with self.assertRaises(StorageError):
                self.ops.allocate(job, self.two.staff_id, 'Change')
        records = self.ops.view()['allocations']
        self.assertEqual(1, len(records))
        self.assertTrue(records[0]['current'])

class IntegratedHttpTests(unittest.TestCase):
    def test_browser_workflow_and_staff_validation(self):
        import threading
        from test_web import BrowserClient
        from norin_delivery.web import DeliveryWebServer
        with tempfile.TemporaryDirectory() as folder:
            app_repo = JsonRepository(Path(folder) / 'records.json')
            gateway = MeknoGateway(DeliveryRepository(Path(folder) / 'delivery.sqlite3'))
            server = DeliveryWebServer(('127.0.0.1', 0), app_repo, gateway)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                client = BrowserClient(server)
                client.request('/api/bootstrap')
                def post(path, **data):
                    status, payload = client.request(path, data)
                    self.assertEqual(200, status, payload)
                    return payload
                state = post('/api/setup', username='manager', password=PASSWORD, confirm_password=PASSWORD)
                self.assertFalse(state['demo_delivery'])
                state = post('/api/delivery/staff', name='Driver', phone='0412345678')
                staff_id = state['delivery_staff'][0]['staff_id']
                post('/api/delivery/availability', staff_id=staff_id,
                     periods=[['2026-11-01 08:00', '2026-11-01 18:00']])
                status, _ = client.request('/api/accounts', dict(username='badstaff', password=PASSWORD,
                    confirm_password=PASSWORD, role='Delivery staff', staff_id='missing'))
                self.assertEqual(400, status)
                post('/api/accounts', username='driver', password=PASSWORD,
                     confirm_password=PASSWORD, role='Delivery staff', staff_id=staff_id)
                state = post('/api/customers', name='Phone Customer', phone='0412345679', email='')
                customer_id = state['customers'][0]['customer_id']
                state = post('/api/requests', customer_id=customer_id, pickup='Melbourne', destination='Hawthorn',
                             parcels=[{'description':'Books'}])
                state = post('/api/quotes', request_id=state['requests'][0]['request_id'], cost='45.50',
                             pickup_time='2026-11-01T09:00', delivery_time='2026-11-01T11:00')
                state = post('/api/quotes/decision', quote_id=state['quotes'][0]['quote_id'], accept=True)
                delivery_id = state['deliveries'][0]['delivery_id']
                post('/api/delivery/allocate', delivery_id=delivery_id, staff_id=staff_id)
                post('/api/logout')
                post('/api/login', username='driver', password=PASSWORD)
                post('/api/delivery/pickup', delivery_id=delivery_id)
                post('/api/delivery/payment', delivery_id=delivery_id, amount='45.50')
                state = post('/api/delivery/complete', delivery_id=delivery_id)
                self.assertEqual('Completed', state['deliveries'][0]['state'])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
