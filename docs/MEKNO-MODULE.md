# Mekno's delivery and staff allocation module

## Run on this Mac

Double-click `Start Your Order.command`, or run:

```sh
/opt/anaconda3/bin/python3.12 run_ui.py
```

Python 3.10+ is required; only standard-library packages are used. The browser
launcher connects the real module. The existing console launcher remains
Norin's quotation demo. `DeliveryWebServer(..., gateway=None)` also retains
its explicit demo fallback for standalone tests; the production `main()`
always supplies `MeknoGateway`.

Use a fresh data file for a demonstration:

```sh
/opt/anaconda3/bin/python3.12 run_ui.py --data data/integrated.json
```

Old accepted `DEMO-DEL-...` quotes are not silently converted. Create new quotes
in the integrated workspace. Existing real customer files were not used in tests.

## Demonstration

1. Create the first manager and sign in.
2. Open **Staff & availability**, add two delivery staff records, and record
   weekly working hours covering their respective pickup and delivery times. Tick
   the relevant Monday-Sunday days and enter clock-in and clock-out times.
3. In **Team accounts**, create delivery-staff accounts using the staff IDs
   displayed in the directory. Unknown/inactive IDs are rejected.
4. Add a phone customer and request with parcels. Submit the request, then
   prepare a quote and record the customer's acceptance.
5. Assign pickup staff, then have that staff member confirm pickup. The job
   becomes **Awaiting delivery assignment**. Assign delivery staff, who may be
   a different person. **Details** shows both allocation records.
6. Demonstrate rejection of overlapping jobs or staff outside their shifts.
   Removing availability releases affected jobs before pickup. If no replacement
   is eligible, the job remains **Awaiting allocation** until office staff assign one.
7. Sign in as the delivery driver: record the exact accepted payment and
   complete the delivery. A driver without the current allocation cannot
   operate the job.
8. Restart the app with the same data path to show retained deliveries,
   schedules, payment, activity and allocation history.

## Classes and responsibilities

| Class | File | Responsibility |
|---|---|---|
| Delivery | `mekno_delivery/models.py` | Accepted terms, lifecycle and references to current allocation/payment |
| DeliveryStaff | `mekno_delivery/models.py` | Staff identity, activity and schedule eligibility |
| AvailabilitySchedule | `mekno_delivery/models.py` | Validated Melbourne working periods and coverage checks |
| StaffAllocation | `mekno_delivery/models.py` | Assignment interval, conflict checks and current/history distinction |

`DeliveryOperations` coordinates authorisation and transactions.
`DeliveryRepository` persists records using SQLite.
`MeknoGateway` implements Norin's accepted-quote boundary.
These are technical collaborators, rather than additional business entities.
The browser uses the existing local HTTP server and existing page styles.

## Rules and persistence

- Managers create/activate/deactivate staff. Office staff and managers allocate
  and release jobs. Drivers edit their own availability and operate only their
  current jobs. Customers see their own deliveries without staff directories.
- Weekly availability repeats every Monday-Sunday. One shift can be entered per
  day. A clock-out earlier than clock-in means the shift ends the next day.
  Shifts cannot overlap. Pickup allocation checks only the estimated pickup
  time; after pickup, delivery allocation checks only the estimated delivery
  time. The pickup assignment ends when pickup is confirmed. Staff must be
  active and free of a conflicting current job at the relevant time. The
  prototype has no route-duration estimate, facility, or parcel handoff record;
  the team must coordinate physical transfer outside the app.
- Dated schedules saved by the earlier version remain readable until a user
  replaces them in the weekly-hours form. They do not silently become recurring.
- Reassignment requires a reason and retains the previous allocation. Failed
  reassignment rolls back both release and creation. At most one allocation is
  current per delivery through the transactional service.
- Availability removal/deactivation releases affected pre-pickup jobs. In-transit
  jobs prevent such changes until office staff reassign the delivery stage with
  a reason. Earlier allocations remain as history.
- Payment uses Tola's existing `Payment.record_collection`. The initial policy
  accepts one exact collection after pickup. Partial payments, refunds and real
  bank transactions are outside this module. Completion requires that payment.
- Lifecycle activity is retained as technical audit records. This does not
  implement Tola's complete StatusEvent/reporting contribution.
- SQLite is stored beside Norin's JSON file: `integrated.delivery.sqlite3` for
  `integrated.json`. SQLite transactions protect staff/schedule/allocation/job
  changes together; `BEGIN IMMEDIATE` serialises writers to this database.
- Norin's JSON store and SQLite do not share a distributed transaction. If the
  JSON acceptance save fails, retry acceptance. The gateway finds the original
  delivery by quote ID and verifies unchanged business terms, keeping the first
  handoff's actor/time audit even if retry audit fields differ. Such an orphan
  delivery is hidden and blocked from allocation until JSON acceptance succeeds.
  Back up and restore both files together. Run one workspace process per JSON
  data file, as required by Norin's existing repository.
- Availability is entered manually; no automatic replacement selection, route
  optimisation, travel buffer, overtime forecasting or live location tracking
  is claimed. Estimates use Melbourne wall-clock time as in the existing code.

## Tests

```sh
/opt/anaconda3/bin/python3.12 -m unittest discover -s tests -v
/opt/anaconda3/bin/python3.12 scripts/verify_and_package.py
```

`tests/test_mekno.py` covers persistent idempotency and conflicting quote terms,
acceptance retry after JSON failure, overlapping/consecutive jobs, reassignment
history, invalid schedules, unavailable replacements, pickup and payment rules,
permissions, transaction rollback, restart and the integrated HTTP workflow.

The code was developed with Codex assistance. Review and understand it, adapt
it as a group, and record actual contributions and assistance according to the
assignment requirements; these notes are not a declaration of sole authorship.
