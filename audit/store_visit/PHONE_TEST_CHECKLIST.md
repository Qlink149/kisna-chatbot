# Store Visit Flow: phone test checklist

**Before you start**
- **Draft Flow:** `kisna_store_visit_draft_v1` (id `2047559429230709`), status DRAFT, not published.
- **Preview:** to run screens 2 and 3 live, the draft needs an endpoint URI pointing at a host running `feat/store-visit` code. See "Preview prerequisites" at the end. Without one, screen 1 renders but **Next** fails.
- **Stores:** loaded in the target DB (item 4 sync, or the seed script on dev).
- **Weekly-off:** no store has one in the kisna.com data. Before row 3.1, set one in the dashboard (Stores → Lulu Mall - Lucknow → weekly off = the next Tuesday's weekday).
- **Dates:** examples assume testing between 28 Sep and 1 Oct 2026. The next holidays are 2 Oct (Gandhi Jayanti) and 20 Oct (Store Holiday).

| # | Step | Expected result | ✔ |
|---|------|-----------------|---|
| **Screen 1: details** | | | |
| 1.1 | Open the form from "book a store visit" | Header "Store Visit". Body is the client pre-form text. Button "Book a Store Visit" | ☐ |
| 1.2 | Look at First name | Prefilled with the WhatsApp profile name | ☐ |
| 1.3 | Look at Phone number | Prefilled with the WhatsApp number (e.g. 91XXXXXXXXXX) | ☐ |
| 1.4 | Leave Last name and Email empty; fill the rest; Next | Goes to screen 2 (both optional) | ☐ |
| 1.5 | Clear Phone number, try Next | Blocked: phone is required. The spec says phone can be left empty; it is required in this build. See note A | ☐ |
| 1.6 | Email `abc@`; Next | Rejected, either by WhatsApp's email field or by "Please enter a valid email address, or leave it blank." | ☐ |
| 1.7 | Leave "What are you looking for?" unselected; Next | Blocked: field is required | ☐ |
| 1.8 | "What are you looking for?" options | Diamond Jewellery, Gold Jewellery, Solitaires, Engagement & Bridal, Gemstone Jewellery, Other | ☐ |
| **Screen 2: store** | | | |
| 2.1 | State dropdown | 25 states, A→Z, only states with a bookable store. "Chhattisgarh" spelled with "hh" | ☐ |
| 2.2 | State = Uttar Pradesh | City dropdown appears with **22** cities, A→Z (Agra … ) | ☐ |
| 2.3 | City = Lucknow | Store dropdown: 5 stores (Alambagh, Hazratganj, Indira Nagar, Lulu Mall, Tiwariganj). The address + PIN shows under each | ☐ |
| 2.4 | State = Delhi → City = Delhi-NCR | **8** stores (the largest store list), address under each | ☐ |
| 2.5 | State = Uttar Pradesh → City = Delhi-NCR | 4 stores (Spectrum Mall - Noida, Sector 18 - Noida, Blue Sapphire Plaza - Greater Noida, Nehru Nagar - Ghaziabad) | ☐ |
| 2.6 | A single-store city: Uttar Pradesh → Kushinagar | Store dropdown with exactly 1 store | ☐ |
| 2.7 | Change State after choosing a city | City list reloads for the new state; the Store dropdown hides until a city is chosen | ☐ |
| 2.8 | Next without a store | Blocked (required), or "Please choose a store." | ☐ |
| 2.9 | Pick a store, Next, then **Back** from screen 3 | Screen 2 shows the same state, city and store still selected | ☐ |
| 2.10 | Back from screen 2 to screen 1 | Screen 1 keeps the typed details | ☐ |
| **Screen 3: date & time** | | | |
| 3.1 | Store with a weekly-off set (Lulu Mall - Lucknow, see before you start) | That weekday is greyed out in the date picker | ☐ |
| 3.2 | Any store, date picker | Range is today → today+6. **2 Oct** is greyed out (holiday) | ☐ |
| 3.3 | Pick today (before ~17:00) | First slot is ≥ 2 h from now (e.g. at 12:45 the first slot is 3:30 PM for a 10:30 store) | ☐ |
| 3.4 | Pick today after the last slot minus 2 h | Today isn't offered; the date picker starts tomorrow | ☐ |
| 3.5 | Pick tomorrow, default store (10:30–20:00) | Slots 10:30 AM … 6:30 PM, hourly (9 slots) | ☐ |
| 3.6 | Non-default hours: Tamil Nadu → Chennai → Nexus Vijaya Mall (10:00–22:00) | Slots 10:00 AM … 9:00 PM (12 slots) | ☐ |
| 3.7 | Non-default hours: Uttar Pradesh → Kanpur → Saket Nagar (11:00–21:30) | Slots 11:00 AM … 8:00 PM (10 slots) | ☐ |
| 3.8 | Change the date | Time list refreshes for the new date | ☐ |
| **Submit** | | | |
| 4.1 | Book Visit | Confirmation arrives: "Your appointment is confirmed! 📍✨", Request ID `KIS-SV-YYYYMMDD-XXXX`, Store: name + address, "Scheduled for: 1 October 2026 · 11:00 AM", then the client's closing lines | ☐ |
| 4.2 | Dashboard → Store Visits | New row with the same request ID, customer, store, visit date/time, status **New** | ☐ |
| 4.3 | Salesforce column on that row | **"Not sent"**: the push is disabled (`KISNA_STORE_VISIT_EVENTS_ENABLED=false`), so no event is queued. See note B | ☐ |
| 4.4 | Tap Book Visit again on the same form (double submit) | Same confirmation and request ID again; still one row in the dashboard | ☐ |
| 4.5 | Change status to Contacted in the dashboard | Badge updates; "by <agent> · <time>" shown | ☐ |
| **Hindi user** | | | |
| 5.1 | New test user: send "मुझे आपके स्टोर पर आना है" | Form arrives; body is the pre-form text in Hindi | ☐ |
| 5.2 | Complete the form and submit | Confirmation in Hindi. Request ID, store name, store address, "1 October 2026" and "11:00 AM" appear **unchanged** (not translated or transliterated) | ☐ |

**Note A (phone field).** The spec lists phone as prefilled and as optional in the empty-fields row. The build makes it required, so every booking has a callable number. If you want it optional, it's one line in `json/store_visit.json`; the booking then falls back to the WhatsApp number.

**Note B (Salesforce).** With the flag off, nothing is written to the outbox, so the event is not queued. If you want it queued but held until the flag is turned on, that needs a small outbox change (a `held` status). Not done yet; say if you want it.

**Preview prerequisites (interactive mode)**
1. A host running `feat/store-visit` whose `/whatsapp/flows/data-exchange` is reachable. Prod runs code without the store-visit screens, so prod can't serve this preview.
2. Create a draft with that endpoint URI. Gupshup ignores endpoint URIs on update, so it has to be a new draft:
   `python scripts/store_visit_flow_draft.py --name kisna_store_visit_draft_v2 --endpoint-uri https://<host>/whatsapp/flows/data-exchange`
3. Open the "preview (interactive)" URL it prints. Screens 2 and 3 then run against the endpoint.
