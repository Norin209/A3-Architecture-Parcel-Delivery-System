# Norin's delivery request and quotation module

Python implementation of Norin's five A2 classes for SWE30003 Assignment 3:
`Customer`, `UserAccount`, `DeliveryRequest`, `Parcel`, and `DeliveryQuote`.
This module covers customer/account registration, delivery request capture,
manual quotation, and acceptance/rejection. It is one part of the group system.

## Open the graphical interface

Double-click **Start Your Order.vbs**. The Python app opens a local browser
workspace with no command-line window. It runs at `http://127.0.0.1:8787`.
Opening the launcher again reopens the same running workspace.

The interface includes a dashboard, searchable/filterable request and quote
tables, request forms with editable parcel rows, quote review/decision dialogs,
customer contact forms, and manager account controls. Menus follow the signed-in
role. Draft forms save as one operation, and errors keep entered values visible.

First use asks you to create the initial manager. Existing console accounts
and `data/records.json` work in the UI as well. Do not run the console and web
app against the same data file at the same time. The graphical server runs
locally in the background after you close a tab. A manager can choose
**Close workspace** in the sidebar to stop it; all saved records remain.

On other computers, or to see startup diagnostics:

```powershell
python run_ui.py
```

The packaged UI is also available as `python Your-Order-UI.pyz`.

No web framework, npm install, external fonts or internet connection is needed.
HTML/CSS/JavaScript provide the presentation; Python still owns business rules,
account access and persistence. The server listens only on loopback, checks
Host/Origin and CSRF tokens, and uses HttpOnly SameSite cookies. Browser sessions
expire after 30 minutes of inactivity. Password hashes are never returned by
the API. This remains a local assignment prototype, not public web hosting.

For a separate practice workspace:

```powershell
python run_ui.py --data data/practice.json --port 8788
```

The delivery handoff is still the labelled demo adapter. Tola's standalone
payment record model is not yet wired to a persisted Delivery or UI workflow;
status and reporting implementations are still outstanding.

## Console version

Double-click **Start Norin Module.cmd** in this folder. It uses the Python
3.11.16 installation found on this computer, or the Windows Python launcher.

On another computer with Python 3.11 or newer installed:

```powershell
cd "path\to\norin-module"
python run.py
```

No third-party packages are required. `python -m norin_delivery` also works.
The packaged `Norin-Module.pyz` can be run with `python Norin-Module.pyz`.
The archive still requires Python; it is not a standalone Windows executable.

On first launch, create a manager username and password. There are **no preset
passwords**. Password input is hidden; type it and press Enter. Then sign in as
the manager to create an office account, or register a customer from the home
menu. Customer self-registration always creates a customer role.

Normal runs store records in `data/records.json`. Each successful operation
saves automatically. To use a separate file:

```powershell
python run.py --data data/practice.json
```

Keep one console open per data file. Files are local, with no server or cloud
account needed. To practise from a clean state, choose a new filename rather
than deleting a file containing useful work.

## Demonstrate Norin's scenarios

1. Create the initial manager, then register a customer from the home menu.
   Try a blank name or invalid email first; the app explains the error.
2. Sign in as that customer. Choose **2 New draft**, select the customer,
   enter pickup/destination addresses and confirm.
3. Choose **3 Edit draft** to add two parcels. Try a blank description,
   then a valid one. Edit a parcel, remove one, or change the locations.
   Removing the last parcel is allowed in a draft but blocks quotation.
4. Sign out. Sign in as manager or office staff. Choose **8 Prepare quote**.
   Try a negative cost or delivery time before pickup, then correct them.
   Example: `45.50`, `2026-11-01 09:00`, `2026-11-01 11:00`.
5. Sign in as the customer, choose **4 Quotes** to review, then **5 Accept/reject
   quote**. Repeated acceptance returns the same reference. Restart the app
   and check that the decision and request remain saved.
6. Create another request/quote to demonstrate rejection. A rejected quote
   cannot become accepted and produces no delivery reference.
7. As office staff or manager, use **7 Add phone customer** to demonstrate
   a customer without an online account. Office staff can record that
   customer's request and decision; the acting account is recorded.

Enter `/cancel` at any prompt to leave the current form without saving it.
Earlier successful operations remain saved. Confirmations let the user
review registration, requests, quotes and decisions before submitting them.

## Integration status

The console uses **DemoDeliveryGateway**, which returns a clearly labelled
`DEMO-DEL-...` reference. It does **not** implement Mekno's `Delivery`, staff
availability/allocation, or Tola's payment, status and reporting workflows.
Thus a demo acceptance is not evidence that the complete group delivery
system works. See `docs/INTEGRATION.md` for the real handoff contract.

Use a separate data file for the integrated system. Do not reuse accepted
demo quotes as real deliveries: they already contain placeholder references.

Manager-created delivery-staff accounts accept an existing staff ID. Creation
and verification of the actual `DeliveryStaff` record belong to Mekno's module.

## Source map

| File | Responsibility |
| --- | --- |
| `norin_delivery/models.py` | The five domain classes, enums and validation |
| `norin_delivery/service.py` | Session, permissions and saved use cases |
| `norin_delivery/storage.py` | Versioned JSON, relationship checks and atomic saves |
| `norin_delivery/integration.py` | Accepted-quote payload and delivery interface |
| `norin_delivery/console.py` | Console input, menus and presentation |
| `norin_delivery/web.py` | Local HTTP API, sessions and browser startup |
| `norin_delivery/static/` | Browser layout, styles and interactions |
| `tola_payment/payment.py` | Immutable payment record and accepted-quote comparison |
| `tests/test_module.py` | Automated business and failure-path tests |
| `tests/test_payment.py` | Payment-record validation and comparison tests |
| `tests/test_web.py` | API isolation, form saves, validation and access tests |
| `scripts/demo_console.py` | Repeatable console walkthrough using temporary data |

The layers are browser -> local API -> application service -> domain/storage/integration.
The console also calls the same application service directly.
The domain classes do not import the console or JSON repository.
`tola_payment.Payment` is a separate domain contribution; its caller must retain
returned records. It does not yet provide storage, a user workflow, bank
processing, partial-payment rules or duplicate-entry protection.

## Verification

Run from this folder:

```powershell
python -m compileall -q norin_delivery run.py
python -m unittest discover -s tests -v
python scripts/demo_console.py
```

The demo uses a temporary directory and does not modify your real records.
Its transcript is an automated demonstration, not evidence of manual group
testing. Capture your own console screenshots/video for report 7.3 and 7.4,
including empty screens, correct/incorrect input, edits and final results.

## Design choices to explain in the report

- Python uses `snake_case` method names; map `createRequest` to `create_request`,
  `validateForQuote` to `validate_for_quote`, and similarly for other methods.
- Records are frozen dataclasses. An edit returns a replacement instead of
  mutating a saved object. The service saves related records together.
- Relationships use stable IDs in JSON. Parcels are contained by their request.
  `Customer.get_requests` filters supplied requests; the application controls
  which records a signed-in user can access.
- `DeliveryQuote.accept` returns an accepted quote. The application calls the
  delivery gateway and saves its returned ID with the quote and request.
  This is a refinement of the report's direct quote-to-Delivery creation.
- `Decimal` preserves exact AUD amounts. Prices must be positive, have at most
  two decimal places, and not exceed 999999.99 (an implementation input limit).
- Estimates are Melbourne local wall-clock values in `YYYY-MM-DD HH:MM`.
  Decision/preparation audit times are UTC. No timezone conversion, daylight
  saving ambiguity resolution or past-date rejection is implemented.
- Names and parcel descriptions cannot be blank. At least a phone or email
  is required; supplied contacts receive basic format checks. These do not
  verify that the contact belongs to the person.
- A draft may have empty locations/no parcels. A quote requires complete
  locations and at least one parcel. Only one quote per request is supported;
  quote revision and cancellation after acceptance are outside this module.
- Username uniqueness is case-insensitive. Passwords use individually salted
  PBKDF2-SHA256 with 600000 iterations. Authority is checked on every saved
  business operation. Deactivation preserves linked records.
- Existing phone customers are selected by office staff for new requests.
  Public registration creates a new customer; it does not automatically merge
  or claim existing customer records based on matching name/email.

This is a single-process assignment prototype. It does not claim to implement
all A1 nonfunctional requirements: timed account lockout, console session expiry,
encryption at rest, multi-user concurrency and disaster recovery remain
outside this module. JSON parse/relationship errors stop loading without
silently resetting the data. A failed save leaves the previous file intact.

## Coding standard and attribution

The source follows Python's PEP 8 naming, indentation and import conventions,
with a project line-length limit of 99 characters. Coding-standard reference:
van Rossum, G., Warsaw, B. and Coghlan, A., *PEP 8 – Style Guide for Python Code*,
https://peps.python.org/pep-0008/ (accessed 27 October 2026).

Business design source: Dy, S. M., Ung, N. and Long, M. (2026), *Assignment 2
Object Design*, SWE30003, especially pp. 10–11 and 17–20.

This starter implementation was generated with Codex assistance. Review,
understand and adapt it as a group, and record actual contributions and
assistance accurately under the unit's requirements. No personal work hours
or statements of independent authorship have been generated.
