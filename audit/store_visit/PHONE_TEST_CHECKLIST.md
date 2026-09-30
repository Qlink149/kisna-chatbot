# Store Visit Flow: phone test checklist

**Before you start**
- **Draft Flow:** `kisna_store_visit_droplet` (id `1750678739319405`), status DRAFT, not published. Endpoint `https://kisna-api.claraai.tech/whatsapp/flows/data-exchange`.
- **Endpoint code:** the live taps (State, City, Next, date) need prod running the branch with the 2-screen layout (`feat/store-visit-test-gate`, or later). With older code the preview fails at the first tap.
- **Same start everywhere:** the WhatsApp send and the interactive preview both use `flow_action=data_exchange`, so screen 1 always comes from the endpoint's INIT. On WhatsApp, INIT prefills the name and number saved when the form was sent (`store_visit_flow_sessions`, keyed by the form's token). The preview has no customer, so it opens with them blank.
- **Interactive preview:** `python scripts/store_visit_flow_draft.py --flow-id 1750678739319405` prints it, with `phone_number` = Kisna's business number from Gupshup (917304278561).
- **Stores:** 170 synced from kisna.com (nightly 02:00 IST).
- **Slot hours:** hourly 11:00 AM … 8:00 PM for every store, unless its open/close is set in Dashboard → Stores (the dashboard shows 11:00–21:00 for those; close is when the last one-hour slot ends). kisna.com's hours no longer set slots.
- **Weekly-off:** no store has one in the kisna.com data. Before row 3.1, set one in the dashboard (Stores → Lulu Mall - Lucknow → weekly off = the next Tuesday's weekday).
- **Dates:** examples assume testing between 29 Sep and 1 Oct 2026. The next holidays are 2 Oct (Gandhi Jayanti) and 20 Oct (Store Holiday).

| # | Step | Expected result | ✔ |
|---|------|-----------------|---|
| **Screen 1: "Schedule a Store Visit!"** | | | |
| 1.1 | Open the form from "book a store visit" (WhatsApp) | Header "Store Visit". Body is the client pre-form text. Button "Book a Store Visit" | ☐ |
| 1.2 | Look at the screen | Title "Schedule a Store Visit!", heading "Find Your Nearest Store". Fields in order: First Name, Last Name (Optional), Email ID (Optional), Phone No (Optional), Looking for, Select your State, Select your City, Nearest Kisna Store. No "*" anywhere; no "missing data-source" error | ☐ |
| 1.2b | Open Select your City and Nearest Kisna Store before picking anything | One greyed-out item each: "Select a state first" / "Select a city first"; can't be picked | ☐ |
| 1.3 | Look at First Name and Phone No (WhatsApp only) | Prefilled with the WhatsApp profile name and number. Phone No shows "Leave blank to use this WhatsApp number" | ☐ |
| 1.4 | Looking for* options | Bracelets, Earrings, Mangalsutra, Necklace, Pendants, Rings (in this order) | ☐ |
| 1.5 | Select your State* | 25 states, A→Z, only states with a bookable store. "Chhattisgarh" spelled with "hh" | ☐ |
| **Typed text survives the cascade (the key check)** | | | |
| 1.6 | Type First Name, Last Name, Email ID and Phone No, pick Looking for, **then** pick State = Uttar Pradesh | Select your City now lists **22** cities. **Every typed field and Looking for are unchanged** | ☐ |
| 1.7 | Now edit Email ID, then pick City = Lucknow | Nearest Kisna Store now lists 5 stores (Alambagh, Hazratganj, Indira Nagar, Lulu Mall, Tiwariganj), address + PIN under each. **The edited email and all other text are unchanged** | ☐ |
| 1.8 | Change State to Delhi | City list reloads (Delhi-NCR); City clears and Store goes back to "Select a city first"; **typed text unchanged** | ☐ |
| 1.9 | City = Delhi-NCR | **8** stores (the largest store list) | ☐ |
| 1.10 | State = Uttar Pradesh → City = Delhi-NCR | 4 stores (Spectrum Mall - Noida, Sector 18 - Noida, Blue Sapphire Plaza - Greater Noida, Nehru Nagar - Ghaziabad) | ☐ |
| 1.11 | Single-store city: Uttar Pradesh → Kushinagar | Exactly 1 store | ☐ |
| **Screen 1 validation (Next)** | | | |
| 1.12 | Leave Last Name, Email ID and Phone No empty; everything else filled; Next | Goes to screen 2 (all three optional) | ☐ |
| 1.13 | Phone No `12345`; Next | Stays on screen 1: "Please enter a valid 10-digit mobile number, or leave it blank." Everything typed and picked is still there | ☐ |
| 1.14 | Email ID `abc@`; Next | Rejected by WhatsApp's email field, or "Please enter a valid email address, or leave it blank." | ☐ |
| 1.15 | Leave First Name, Looking for or Nearest Kisna Store empty | Next stays disabled (required) | ☐ |
| **Screen 2: "Choose Date & Time"** | | | |
| 2.1 | Store name + address shown at the top | The store picked on screen 1 | ☐ |
| 2.2 | Back to screen 1 | All text, State, City and Store still as entered | ☐ |
| 2.3 | Store with a weekly-off set (Lulu Mall - Lucknow, see before you start) | That weekday is greyed out | ☐ |
| 2.4 | Any store, date picker | Range is today → today+6. **2 Oct** greyed out (holiday) | ☐ |
| 2.5 | Pick today (before ~17:00) | First slot ≥ 2 h from now, on the hour (e.g. at 12:45, first slot 3:00 PM) | ☐ |
| 2.6 | Pick tomorrow, any store whose hours weren't set in the dashboard | Slots 11:00 AM … 8:00 PM, hourly (10 slots) — the client's default | ☐ |
| 2.7 | kisna.com hours no longer count: Tamil Nadu → Chennai → Nexus Vijaya Mall (kisna.com lists 10:00–22:00) | Still 11:00 AM … 8:00 PM (10 slots) | ☐ |
| 2.8 | Dashboard hours win: Dashboard → Stores → Saket Nagar - Kanpur → open 10:00, close 18:00 → save. Then Uttar Pradesh → Kanpur → Saket Nagar, tomorrow | Slots 10:00 AM … 5:00 PM (8 slots; a slot must end by close). Afterwards set it back to 11:00–21:00 | ☐ |
| 2.9 | Change the date | Time list refreshes for the new date | ☐ |
| **Submit (WhatsApp only; a preview submit creates no booking)** | | | |
| 3.1 | Tap **Submit** | Confirmation: "Your appointment is confirmed! 📍✨", Request ID `KIS-SV-YYYYMMDD-XXXX`, Store: name + address, "Scheduled for: 1 October 2026 · 11:00 AM", then the client's closing lines | ☐ |
| 3.2 | Dashboard → Store Visits | New row: same request ID, customer, store, visit date/time, status **New**. With Phone No left blank, mobile = the WhatsApp number | ☐ |
| 3.3 | Salesforce column on that row | **"Not sent"**: the push is off (`KISNA_STORE_VISIT_EVENTS_ENABLED` unset). See note B | ☐ |
| 3.4 | Tap Submit again on the same form | Same confirmation and request ID; still one row | ☐ |
| 3.5 | Change status to Contacted in the dashboard | Badge updates; "by <agent> · <time>" shown | ☐ |
| **Hindi user** | | | |
| 4.1 | Test number: send "मुझे आपके स्टोर पर आना है" | Form arrives; body is the pre-form text in Hindi | ☐ |
| 4.2 | Complete and submit | Confirmation in Hindi. Request ID, store name, store address, "1 October 2026" and "11:00 AM" appear **unchanged** | ☐ |
| **Go-live (test-number gate removed)** | | | |
| 5.1 | With `KISNA_STORE_VISIT_TEST_NUMBERS` removed from the env, from any number: "book a store visit" | The form arrives; log `Store visit offer ... path: form, reason: all_numbers` | ☐ |

**If 1.6–1.8 fail** (typed text cleared when State or City changes): tell me. The endpoint already sends every typed field back as the form's init-values on each refresh (tested), so a failure means WhatsApp ignores init-values on a same-screen refresh. The fix is to put the cascade back on its own screen, as in the previous layout.

**Note A (phone field).** Phone No is prefilled and optional. Left blank, the booking uses the WhatsApp number.

**Note B (Salesforce).** With the flag off, nothing is written to the outbox. When the push is turned on, send the bookings made in the meantime with `python scripts/backfill_store_visit_events.py --dry-run` (lists them), then without `--dry-run`. It's idempotent on request ID.
