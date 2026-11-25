# Which information is public and which is private

*For review by the Campus Security Office. Last updated with v1.*

This document lists exactly what the Lost & Found system shows to the public, and what it keeps private. "Public" means anyone can see it on the public board or through the public API (`/` and `/api/board/`), without logging in.

---

## A. Public – shown on the board for every item

These are the **only** pieces of information the public board shows. The list is fixed in the code (`apps/board/public.py`, `PUBLIC_FIELDS`), and an automated test fails if anything is added to it without the code being changed deliberately.

| # | Information | Example | Notes |
|---|---|---|---|
| 1 | Item number | 42 | |
| 2 | Lost or found | "Found" | |
| 3 | Short title | "Black backpack" | Written by the reporter |
| 4 | Public description | "Left under a chair" | Written by the reporter, who is told not to put identifying details here |
| 5 | Category name and icon | 🎒 Bags | |
| 6 | General attributes | colour: black, brand: Wildcraft | Only the attributes the category asks for (e.g. colour, brand) |
| 7 | Location | "Central Library › Ground Floor Reading Hall" | Campus area only; no GPS |
| 8 | Date | 2026-11-24 | **Date only, no time** |
| 9 | Public status | "At security desk", "Claim in progress", "Returned" | Simplified wording; internal workflow details are hidden |
| 10 | Can be claimed? | yes/no | |
| 11 | Photo | | **Only if the reporter ticked "Show photo on the public board"**. For found items this is **off** by default. All location data (GPS) and camera information are removed from every photo before it is saved. |

## B. Private – never shown on the public board or public API

| Information | Who can see it |
|---|---|
| **Hidden identifying details** (questions and answers entered by the finder, e.g. "Sticker on the back? → NASA logo") | The finder who entered them, and Security personnel. **Encrypted** in the database. Claimants see **only the questions**, during their verification, never the answers. |
| Name, email, phone and campus ID of the person who reported the item | Security personnel |
| Exact time the item was lost or found | The reporter and Security |
| Who has claimed an item, and their claim statement | The claimant and Security |
| Claimants' answers to verification questions, and their scores | Security personnel (verification review page) |
| Custody chain (where the item is held, who handled it) | Security personnel. The reporter sees a simplified version on their own report. |
| Handover code (OTP) | Only the claimant, sent by notification and email. The system stores only a one-way fingerprint (hash) of it, so not even administrators can read it back. |
| Handover proof photo, signature, ID-document note | Security personnel |
| Disposal records | Security personnel |
| Audit log | Security personnel (read-only; nobody can edit or delete entries) |

## C. How this is enforced

1. Hidden details are stored in a **separate, encrypted table**. The software has no link from an item to its hidden details, so a page that shows an item cannot accidentally show them.
2. All public pages and the public API use **one shared allow-list** (section A). Nothing outside that list can be sent.
3. An **automated test** creates an item with marker words in its hidden details, puts the item through **every possible status** (open, in custody, claim pending, approved, returned, ageing, awaiting disposal, disposed, withdrawn, resolved), and checks that none of the marker words appear on any public page or in the public API, whether the visitor is logged out or logged in as an unrelated user. A second test checks that a claimant never sees the answers.
4. Hidden details are **not available in the administration panel** (`/admin/`).

## D. Changing this list

Adding anything to section A is a security decision. It requires:
1. A change to `apps/board/public.py` (`PUBLIC_FIELDS` and `to_public`),
2. A change to the automated test `tests/test_structure.py`,
3. An update to this document, reviewed by the Security Office.
