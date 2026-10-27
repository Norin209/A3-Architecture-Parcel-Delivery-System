# Your Order interface

## Visual direction

A quiet green-and-cream delivery workspace: a fixed white navigation sidebar,
soft neutral canvas, deep-green primary actions and restrained status colours.
System fonts keep the application offline and avoid extra setup. Original inline
SVG icons provide consistent visual cues without downloading an icon library.

The browser interface scales from a two-column desktop dashboard to a single
column on small screens. On narrow screens a menu button reveals navigation;
tables scroll within their own containers and forms stack their fields.

## Screens and tasks

| Screen | Purpose |
| --- | --- |
| First-run setup | Create the initial manager without predefined passwords |
| Sign in / customer registration | Enter the workspace with the appropriate role |
| Overview | Counts from actual records, next action, recent requests and pending quote value |
| Delivery requests | Search/filter records, inspect routes, create and edit drafts |
| Request form | Select customer, enter locations, add/edit/remove parcel descriptions |
| Quotes | Filter decisions, inspect price/times, accept or reject with confirmation |
| Customers / My details | Update contact details while preserving linked history |
| Team accounts | Manager-only staff registration and account deactivation |

## Interaction choices

- Empty states explain how to begin, rather than displaying invented activity.
- Drafts may be incomplete; quotation validates the required details.
- The request editor saves all entered locations and parcels in one transaction.
  Cancelling the dialog leaves the stored request unchanged.
- Inline errors preserve form values. Submit buttons disable while a save is
  in progress. Success notifications confirm the result.
- Issued requests are read-only. Quote decisions require a second confirmation
  showing what acceptance or rejection means.
- Text accompanies status colours. Controls have labels, visible keyboard focus
  and accessible names. Native modal dialogs support Escape and focus trapping.
- Search is limited to records the signed-in user is permitted to read. UI menu
  visibility supplements server-side authorisation; it does not replace it.
- Demo delivery references are identified where a customer reviews acceptance.
  No screen claims that an actual delivery job has been created by the demo.

## Report changes

Sections 5 and 6 should now describe a local browser presentation over a Python
application/domain layer and JSON persistence. The GUI adds `DeliveryWebServer`,
`WebHandler` and `Session` technical classes. The domain class responsibilities
remain intact. `create_request` accepts optional initial parcel descriptions,
and `save_draft` atomically applies a complete request-edit form.

This interface does not complete the other group members' operational areas.
The overall A3 implementation still needs their modules and integrated evidence.

## Verification status

JavaScript syntax, Python compilation and HTTP/business tests are automated.
The browser automation tool could not verify the current Chrome URL and stopped
computer use, so a rendered visual review and manual GUI walkthrough have not
been completed. Do not describe this as user-tested or visually verified yet.

Manual checks to perform when opening the app:

1. Check setup/sign-in and the empty dashboard at desktop and narrow widths.
2. Create a request with two parcels; edit one and remove one; cancel another
   edit and confirm the saved request is unchanged.
3. Prepare an invalid quote, correct its price/times, and issue it.
4. Review and accept or reject a quote under the customer account.
5. Reopen the app and confirm data persists and customer data stays isolated.
6. Capture the initial, valid-input, validation, edit and result screens for A3.

`scripts/seed_ui_preview.py --data <new-file>` optionally creates explicitly
artificial preview records. It refuses to overwrite an existing file; never
use it on the group's real saved records. Preview passwords are test-only.
