"""SQLite transactions protect delivery records and allocation history together.

Each table stores typed records as JSON. BEGIN IMMEDIATE serialises competing
writers, including separate processes. Quote terms are snapshotted unchanged.
"""
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from norin_delivery.storage import StorageError
from .models import Delivery, DeliveryStaff, AvailabilitySchedule, StaffAllocation

TYPES = {'deliveries': Delivery, 'staff': DeliveryStaff,
         'schedules': AvailabilitySchedule, 'allocations': StaffAllocation}
KEYS = {'deliveries': 'delivery_id', 'staff': 'staff_id',
        'schedules': 'staff_id', 'allocations': 'allocation_id'}


class DeliveryRepository:
    def __init__(self, path):
        self.path = Path(path)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path) as db:
                version = db.execute('PRAGMA user_version').fetchone()[0]
                if version not in (0, 1):
                    raise StorageError('Unsupported delivery database version.')
                for table in TYPES:
                    db.execute(f'CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
                db.execute('CREATE TABLE IF NOT EXISTS payments (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
                db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
                db.execute('PRAGMA user_version=1')
        except (OSError, sqlite3.Error) as exc:
            raise StorageError('Cannot open delivery database.') from exc

    @contextmanager
    def transaction(self):
        try:
            with sqlite3.connect(self.path, timeout=10) as db:
                db.execute('BEGIN IMMEDIATE')
                yield db
        except sqlite3.Error as exc:
            raise StorageError('Unable to save delivery changes.') from exc

    @staticmethod
    def all(db, table):
        result = []
        for (payload,) in db.execute(f'SELECT payload FROM {table} ORDER BY rowid'):
            data = json.loads(payload)
            if table == 'schedules':
                data['periods'] = tuple(tuple(x) for x in data['periods'])
            result.append(TYPES[table](**data))
        return result

    @classmethod
    def get(cls, db, table, identifier):
        from norin_delivery.models import DomainError
        for record in cls.all(db, table):
            if getattr(record, KEYS[table]) == identifier:
                return record
        raise DomainError(f'{table.capitalize()} record not found.')

    @staticmethod
    def save(db, table, record):
        db.execute(f'INSERT OR REPLACE INTO {table} VALUES (?, ?)',
                   (getattr(record, KEYS[table]), json.dumps(asdict(record))))
