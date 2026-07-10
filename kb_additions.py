"""
KISNA KNOWLEDGE BASE — ADDITIONS (July 2026)
Sources: kisna.com/digital-gold, meriroshni.kisna.com

HOW TO USE:
1. In your knowledge_base.py (or wherever KISNA_KNOWLEDGE_BASE is defined):
   a. REPLACE the existing ## DIGITAL GOLD (SafeGold) section with DIGITAL_GOLD_SECTION below.
   b. APPEND KMR_SECTION to the end of KISNA_KNOWLEDGE_BASE (before the closing triple-quote).
2. If you are past the ~12k token threshold and using Chroma RAG instead of
   prompt-injection, re-run scripts/ingest_knowledge_base.py after updating.
"""

# ─────────────────────────────────────────────────────────────────────────────
# REPLACE the existing ## DIGITAL GOLD (SafeGold) section in KISNA_KNOWLEDGE_BASE
# with the content below.
# ─────────────────────────────────────────────────────────────────────────────

DIGITAL_GOLD_SECTION = """\
## DIGITAL GOLD (SafeGold) — kisna.com/digital-gold
- Platform: Kisna Digital Gold is powered by SafeGold, a product offered by Digital Gold India Private Limited (DGIPL). It is NOT a financial instrument or deposit scheme — it is a way to purchase 24K gold for personal use.
- On each successful payment, physical gold is purchased on the customer's behalf and the quantity (accurate to 4 decimal places) is credited to their account.

### Eligibility & Account
- Who can buy: any Indian citizen with a valid PAN card. NRIs are NOT permitted to buy, sell, or redeem Kisna Digital Gold.
- Registration: online ONLY at kisna.com/digital-gold — provide name, mobile number, email, PIN code, and PAN.
- At physical stores: customers may ONLY redeem their SafeGold balance. Buying and selling are available exclusively on the Kisna website.
- Joint accounts: NOT permitted.
- Account inactive/suspended: contact DGIPL customer service for reactivation; Kisna customer service is a secondary support channel.

### Purity & Pricing
- Purity: 24 Karat, 995 fineness (99.5% pure gold or higher).
- Minimum purchase: ₹10. No upper limit (subject to successful KYC verification).
- No lock-in period — one-time purchase with no obligation for recurring payments.
- Rate note: SafeGold price reflects real-time commodity/market rates. Kisna's e-commerce gold price is higher because it includes manufacturing, processing, and operational costs across the jewellery value chain. SafeGold prices fluctuate throughout the day.

### Buying
- Cheque payments (including post-dated cheques): NOT accepted — fully digital product only.
- Order cancellation: NOT possible once a digital gold purchase order is placed.
- Invoice: downloadable from the platform directly.
- Holding statement: always available on the platform.

### Storage & Safety
- Gold is stored with Brink's (global precious metal vaulting leader). Fully insured during storage and transit.
- Administrator: Vistra Corporate Services (India) Private Limited — holds a charge over all stored gold, ensuring customer gold is protected and segregated regardless of DGIPL's operational status.
- Storage duration: up to 10 years from purchase date. Free for the first 5 years; a nominal custody fee applies after 5 years (customer notified before any charge; option to sell or request delivery).
- If DGIPL goes into liquidation: customer holdings are legally separate from DGIPL's corporate assets. The Administrator retains a charge. Physical gold is NOT treated as DGIPL's asset. Redemption dispatched via reputable logistics provider upon request.

### Selling
- Can sell any portion of holdings at the live sell rate.
- Minimum sell amount: ₹100, up to total gold owned.

### Redemption (converting SafeGold balance to jewellery)
- Balance converts at the current SafeGold sell rate ("Redemption Value"). Jewellery price (gold rate + making + fees) is "Purchase Value". Customer pays the difference if Purchase Value > Redemption Value.
- Online: add to cart → checkout → select "Digital Gold" → enter amount (minimum ₹100) → OTP confirmation → balance applied.
- In-store: share registered mobile number + redemption amount → OTP → balance adjusted; store discounts/offers still apply.
- Waiting period: redemption is only allowed 3 working days AFTER the digital gold purchase date.
- Redeemable only at Kisna stores / kisna.com. Digital gold from other platforms is NOT eligible at Kisna.
- Kisna SafeGold balance cannot be redeemed at other jewellery brands.
"""

# ─────────────────────────────────────────────────────────────────────────────
# APPEND the content below to the END of KISNA_KNOWLEDGE_BASE (before the
# closing triple-quote).
# ─────────────────────────────────────────────────────────────────────────────

KMR_SECTION = """\
## KISNA MERI ROSHNI (KMR) — Monthly Savings Plan — meriroshni.kisna.com
- KMR is Kisna's "10+1" monthly jewellery savings plan with two variants: KMR-Amount and KMR-Gram.
- How to join: visit any Kisna exclusive store (store staff will assist), or enroll online at meriroshni.kisna.com.
- Support phone: 8065155600.

### KYC Requirements
- Aadhaar Card or Passport required at store enrollment.
- PAN Card required if the monthly installment amount is ₹19,000 or above.
- PAN Card mandatory at redemption for any redemption value above ₹2,00,000 (per RBI guidelines).

### Installment Rules
- Minimum monthly installment: ₹2,000 (in multiples of ₹500 — e.g. ₹2,000 / ₹2,500 / ₹3,000). No maximum cap.
- Installment amount cannot be changed after the plan has started.
- Due date: same date each month as the first installment (e.g. paid on 5th Jan → next due 5th Feb).
- No additional benefit for paying early or in advance.
- Confirmation: provided via email, SMS, and an online passbook/dashboard (payments, status, installments paid, due dates).

### Payment Options
- Online: Credit card, Debit card, Net banking, UPI.
- In-store (at any Kisna exclusive store): cash, card, cheque, demand draft.
- Failed online payment: wait 48 hours. If not credited after 48 hours, contact support with a payment screenshot and issue details.
- Subsequent installments can be paid at ANY Kisna exclusive store or on the website — not locked to enrollment location.

### KMR-Amount Plan
- Pay a fixed installment for 10 months. The 11th month's installment value is given by Kisna as a discount at redemption.
- Maturity benefit:
  - Diamond jewellery: 100% discount equivalent to the 1st installment value.
  - Gold jewellery: 75% discount equivalent to the 1st installment value.
- Example: ₹2,000/month × 10 months → Kisna gives ₹2,000 discount for diamond jewellery, or ₹1,500 for gold jewellery.
- Ongoing Kisna promotions/offers can be combined at maturity or pre-maturity redemption.

### KMR-Gram Plan (Gold Saving Scheme)
- Each monthly installment is converted into 24KT gold grams at the live gold rate on the payment date (provides price protection if gold prices rise later).
- Structure: 10 monthly deposits; a bonus gram month is credited at maturity.
- Maturity benefit:
  - Diamond jewellery: 100% of the bonus month's gold gram value.
  - Gold jewellery: 75% of the bonus month's gold gram value.
- At redemption: all accumulated grams are converted to value at the current gold rate on the redemption date.
- Example (₹10,000/month): over 10 months at varying rates → 11.635g accumulated → at ₹10,940/gram on redemption day → redeem value ₹1,27,287. Diamond bonus = 0.914g extra; Gold bonus = 0.686g extra.

### Defaulting & Early Closure
- Defaulting any installment: the maturity benefit is forfeited. Customer receives only the total paid principal at maturity.
- Early closure (anytime before maturity): can withdraw paid installments; gets back principal only, no benefit. Refund remitted to bank account within 15 banking working days. Cash refunds are NOT given.

### Pre-Maturity Redemption
- Eligible after paying more than 6 monthly installments (but before completing all installments).
- Pre-maturity benefit:
  - Diamond jewellery: 50% of the 1st installment value as discount.
  - Gold jewellery: 37.5% of the 1st installment value as discount.
- KMR-Gram pre-maturity: Diamond = 50% of bonus grams; Gold = 37.5% of bonus grams.
- Example: ₹2,000/month → pre-maturity diamond discount = ₹1,000; pre-maturity gold discount = ₹750.

### Redemption Rules
- Where to redeem: any Kisna exclusive store or kisna.com — not restricted to the enrollment store.
- Eligible products: diamond jewellery and gold jewellery ONLY.
- NOT eligible for redemption: Gold Coins, Silver Coins, Rare Solitaire, Plain Platinum jewellery, Studded Diamond Platinum jewellery.
- Cannot split redemption across categories — one plan must redeem entirely for EITHER diamond OR gold jewellery, not a mix.
- If redemption invoice value > plan value: customer pays the difference. No refunds, carry-forward credit notes, or advance vouchers are issued.
- Combining plans: two plans can be combined (e.g. for family members) with written consent of plan holders; billing invoice in one holder's name.
- Third-party redemption: a friend or relative can redeem on the customer's behalf by completing the required mandatory processes.
- Non-redemption after maturity: Kisna waits up to 365 days from the 1st installment date, then refunds the entire paid principal (without any benefit) to the customer's bank account.
- Cash withdrawal instead of jewellery: NOT allowed under any circumstances.
"""
