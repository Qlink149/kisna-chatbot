# Quick Smoke Test — native script + recent fixes

Send each line on WhatsApp. [RESET] = send "hi" fresh first. ✅ = pass criteria.
Priority order: native script first (highest risk), then the specific bug fixes.

## 1. NATIVE SCRIPT — the big one  [RESET first]

1. `मुझे 4 हज़ार से ज़्यादा कीमत वाली अंगूठी चाहिए`
   ✅ Shows RING products (images + Buy on KISNA). NOT a handoff, NOT "connecting
   to a representative", NOT a budget question.

2. `५० हज़ार से ज़्यादा कीमत वाला नेकलेस दिखाओ`
   ✅ Necklaces above ₹50k, shown as products. Reply text in Hindi.

3. `મારે ૪૦ હજારથી વધુ કિંમતની બુટ્ટી જોઈએ છે`
   ✅ Earrings above ₹40k, products shown. Reply in Gujarati.

4. `सोने की अंगूठी दिखाओ`
   ✅ Gold rings shown. (Devanagari understood.)

5. (continue from 4, same chat) `अब नेकलेस दिखाओ`
   ✅ Switches to NECKLACES — not more rings, not stale results.

## 2. Native non-product intents  [RESET before each]

6. `आज सोने का भाव क्या है?`
   ✅ Gold rate chart.

7. `મારે રિટર્ન કરવું છે`
   ✅ Return/complaint handling (form or honest flow), reply in Gujarati.

## 3. Silver / gemstone honesty  [RESET before each]

8. `क्या आपके पास चांदी की अंगूठी है?` (do you have silver rings?)
   ✅ Honest: we do gold/diamond/gemstone, NOT silver. Must NOT call products
   "silver" or show products labelled silver.

9. `Do you sell gemstone jewellery?`
   ✅ YES — confirms gemstone. Must NOT deny it.

10. `silver ki ring dikhao`
    ✅ Same honesty as #8 (romanized).

## 4. Careers / head office  [RESET before each]

11. `mujhe kisna mein job chahiye`
    ✅ Points to careers page (kisna.com/careers-and-job-opportunities) +
    hr@kisna.com. Must NOT invent "kisna.com/careers" or overpromise help with
    a specific position.

12. `head office ka address kya hai?`
    ✅ Does NOT give the street address. Offers to find nearest store instead.

## 5. Language mirroring  [RESET before each]

13. `sone ki anguthi dikhao`
    ✅ Reply in Hinglish (Latin), NOT Devanagari.

14. `hii kaise ho`
    ✅ Warm natural reply ("Main badhiya! Aap batao…"), varied — not the same
    canned welcome twice.

## 6. Core regression (romanized) — make sure nothing broke  [RESET first]

15. `show me diamond rings`  → ✅ rings + CTA
16. `under 50000`           → ✅ filtered ≤50k (inherits rings)
17. `thoda sasta dikhao`    → ✅ cheaper (~30% below)
18. `necklaces under 30k`   → ✅ NECKLACES (not rings)
19. `iska price kya hai?`   → ✅ recaps shown items with prices, asks which
20. `25-30k rings`          → ✅ ₹25,000–₹30,000 range (not 28,500–31,500)

## 7. Flows still fire  [RESET before each]

21. `I want to raise a complaint`   → ✅ complaint form
22. `can you schedule a video call?`→ ✅ video-call form
23. `kisna store near me` → `313001` → ✅ asks pincode, then Udaipur store

---

Watch for, on ANY message:
- A handoff / "connecting to representative" when you asked for products (native bug)
- Reply in the WRONG script/language
- Products labelled with a material they aren't (e.g. "silver")
- A menu/list/buttons appearing (should be none except the 5 forms + CTA links)
- `**literal asterisks**` in the text
- Same canned line repeated verbatim

Paste replies grouped by number; I'll diagnose anything that misses.
