# Store Visit Flow: phone test checklist

**Before you start**
- **Draft Flow:** `kisna_store_visit_droplet` (id `1750678739319405`), status DRAFT, not published. Endpoint `https://kisna-api.claraai.tech/whatsapp/flows/data-exchange`.
- **Endpoint code:** the live taps (State, City, Next, date) need prod running the branch with the 2-screen layout (`feat/store-visit-test-gate`, or later). With older code the preview fails at the first tap.
- **Interactive preview:** `python scripts/store_visit_flow_draft.py --flow-id 1750678739319405` prints it. It uses `flow_action=data_exchange`, so screen 1 comes from the endpoint (INIT), and `phone_number` = Kisna's business number from Gupshup (917304278561). In the preview, name and phone are not prefilled (there's no customer); on WhatsApp they are.
- **Stores:** 170 synced from kisna.com (nightly 02:00 IST).
- **Weekly-off:** no store has one in the kisna.com data. Before row 3.1, set one in the dashboard (Stores → Lulu Mall - Lucknow → weekly off = the next Tuesday's weekday).
- **Dates:** examples assume testing between 29 Sep and 1 Oct 2026. The next holidays are 2 Oct (Gandhi Jayanti) and 20 Oct (Store Holiday).

| # | Step | Expected result | ✔ |
|---|------|-----------------|---|
| **Screen 1: "Schedule a Store Visit!"** | | | |
| 1.1 | Open the form from "book a store visit" (WhatsApp) | Header "Store Visit". Body is the client pre-form text. Button "Book a Store Visit" | ☐ |
| 1.2 | Look at the screen | Title "Schedule a Store Visit!", heading "Find Your Nearest Store". Fields in order: First Name*, Last Name, Email ID, Phone No, Looking for*, Select your State*. City and Store appear later | ☐ |
| 1.3 | Look at First Name* and Phone No (WhatsApp only) | Prefilled with the WhatsApp profile name and number. Phone No shows "Leave blank to use this WhatsApp number" | ☐ |
| 1.4 | Looking for* options | Diamond Jewellery, Gold Jewellery, Solitaires, Engagement & Bridal, Gemstone Jewellery, Other | ☐ |
| 1.5 | Select your State* | 25 states, A→Z, only states with a bookable store. "Chhattisgarh" spelled with "hh" | ☐ |
| **Typed text survives the cascade (the key check)** | | | |
| 1.6 | Type First Name, Last Name, Email ID and Phone No, pick Looking for, **then** pick State = Uttar Pradesh | Select your City* appears with **22** cities. **Every typed field and Looking for are unchanged** | ☐ |
| 1.7 | Now edit Email ID, then pick City = Lucknow | Nearest Kisna Store* appears with 5 stores (Alambagh, Hazratganj, Indira Nagar, Lulu Mall, Tiwariganj), address + PIN under each. **The edited email and all other text are unchanged** | ☐ |
| 1.8 | Change State to Delhi | City list reloads (Delhi-NCR); City and Store selections clear; **typed text unchanged** | ☐ |
| 1.9 | City = Delhi-NCR | **8** stores (the largest store list) | ☐ |
| 1.10 | State = Uttar Pradesh → City = Delhi-NCR | 4 stores (Spectrum Mall - Noida, Sector 18 - Noida, Blue Sapphire Plaza - Greater Noida, Nehru Nagar - Ghaziabad) | ☐ |
| 1.11 | Single-store city: Uttar Pradesh → Kushinagar | Exactly 1 store | ☐ |
| **Screen 1 validation (Next)** | | | |
| 1.12 | Leave Last Name, Email ID and Phone No empty; everything else filled; Next | Goes to screen 2 (all three optional) | ☐ |
| 1.13 | Phone No `12345`; Next | Stays on screen 1: "Please enter a valid 10-digit mobile number, or leave it blank." Everything typed and picked is still there | ☐ |
| 1.14 | Email ID `abc@`; Next | Rejected by WhatsApp's email field, or "Please enter a valid email address, or leave it blank." | ☐ |
| 1.15 | Leave First Name*, Looking for* or Nearest Kisna Store* empty | Next stays disabled (required) | ☐ |
| **Screen 2: "Choose Date & Time"** | | | |
| 2.1 | Store name + address shown at the top | The store picked on screen 1 | ☐ |
| 2.2 | Back to screen 1 | All text, State, City and Store still as entered | ☐ |
| 2.3 | Store with a weekly-off set (Lulu Mall - Lucknow, see before you start) | That weekday is greyed out | ☐ |
| 2.4 | Any store, date picker | Range is today → today+6. **2 Oct** greyed out (holiday) | ☐ |
| 2.5 | Pick today (before ~17:00) | First slot ≥ 2 h from now (e.g. at 12:45, first slot 3:30 PM for a 10:30 store) | ☐ |
| 2.6 | Pick tomorrow, default store (10:30–20:00) | Slots 10:30 AM … 6:30 PM, hourly (9 slots) | ☐ |
| 2.7 | Non-default hours: Tamil Nadu → Chennai → Nexus Vijaya Mall (10:00–22:00) | Slots 10:00 AM … 9:00 PM (12 slots) | ☐ |
| 2.8 | Non-default hours: Uttar Pradesh → Kanpur → Saket Nagar (11:00–21:30) | Slots 11:00 AM … 8:00 PM (10 slots) | ☐ |
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
| **Test-number gate** | | | |
| 5.1 | From a number NOT in `KISNA_STORE_VISIT_TEST_NUMBERS`: "book a store visit" | Only the store locator link; log `Store visit offer ... path: locator_link, reason: not_a_test_number` | ☐ |

**If 1.6–1.8 fail** (typed text cleared when State or City changes): tell me. The endpoint already sends every typed field back as the form's init-values on each refresh (tested), so a failure means WhatsApp ignores init-values on a same-screen refresh. The fix is to put the cascade back on its own screen, as in the previous layout.

**Note A (phone field).** Phone No is prefilled and optional. Left blank, the booking uses the WhatsApp number.

**Note B (Salesforce).** With the flag off, nothing is written to the outbox. When the push is turned on, send the bookings made in the meantime with `python scripts/backfill_store_visit_events.py --dry-run` (lists them), then without `--dry-run`. It's idempotent on request ID.
