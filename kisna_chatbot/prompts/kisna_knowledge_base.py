"""
KISNA Knowledge Base — single source of truth for the GeneralAgent (KIA).

Condensed from the official KISNA team knowledge base (June 2026).
All numbers are the resolved authoritative values. Do NOT approximate
or let the model round these — quote them exactly.

When this KB exceeds ~12k tokens, switch GeneralAgent from prompt-injection
to Chroma kb_search() retrieval. Ingestion is handled by
scripts/ingest_knowledge_base.py.
"""

KISNA_KNOWLEDGE_BASE = """\
# KISNA KNOWLEDGE BASE (authoritative source of truth)

## COMPANY
- Brand: KISNA (Diamond & Gold Jewellery), by Hari Krishna Group / Hari Krishna Exports Pvt. Ltd.
- Founded: 2005 (Kisna brand launched in Mumbai); Hari Krishna Group established 1992.
- Founder: Shri Savji Dholakia — Padma Shri awardee (2022).
- Headquarters: The Capital, BKC, Bandra East, Mumbai, Maharashtra 400051.
- Footprint: 120+ flagship stores; 3,500+ retail touchpoints across 29 Indian states.
- Products: Diamond & gold jewellery — rings, earrings, pendants, mangalsutras, bangles, bracelets, necklaces, nose pins, chains, and a 9KT gold line.
- All natural diamonds set in 14KT/18KT gold; every piece is hallmarked.
- Sister brands: Kisna, Siva, RARE, Platinum, Oro, Rang.

## BRAND PROMISE
- Certified jewellery (BIS Hallmark for gold; IGI/GIA for diamonds).
- 7-day money-back guarantee.
- Free shipping within India.
- Easy exchange & buyback.
- Free jewellery insurance.
- EMI options available.
- Uniform pricing across website, app, and physical stores.

## RETURNS POLICY (authoritative)
- Return window: 7 days, no-questions-asked, from date of receipt.
- Eligibility: item must be unworn/unused, in original condition, with tags and original packaging, plus receipt/proof of purchase.
- How to return: the customer must REQUEST a return FIRST — contact support by phone (+91 80651 55600) or email (support@kisna.com). Kisna arranges pickup once approved. Items shipped back WITHOUT a prior request are NOT accepted.
- Damaged/wrong item: inspect on receipt and report immediately for evaluation.
- Exclusions: sale items and gift cards are NOT eligible for return.
- Refunds: if approved within the 7-day window, customer gets a 100% refund to the original payment method, processed within 10 business days (bank/card processing may add delay).
- Return shipping: a flat ₹100 charge applies to resizing, exchange, and refund shipments sent back to Kisna.
- Partial returns: allowed per individual item, but each returned product must be returned in full, including all components.
- Ring doesn't fit: check the size guide before ordering; if it still doesn't fit, send it back for resizing/exchange.
- Track a return: via chat support or by emailing support@kisna.com.

## EXCHANGE POLICY (authoritative — /buyback-and-exchange-policy)
- Applies to products sold in India, available for the lifetime of the product, but only 7+ days after purchase date, subject to Quality Assurance review (item must be free of tampering, damage, alteration, or resizing — otherwise rejected).
- Diamond jewellery: 95% of current product price (excl. GST); labour charges NOT deducted; any original discounts/offers are deducted.
- Gold jewellery: 100% of current gold value.
- Required: original product + original invoice + product certificate (a missing diamond certificate incurs a charge).
- Old gold (distinct from Kisna-jewellery exchange): can be exchanged at any physical Kisna store for 100% value, no deductions.

## BUYBACK POLICY (authoritative)
- Diamond jewellery: 90% of current product price (excl. GST); discounts/offers deducted.
- Gold jewellery: 97% of current gold value.
- Required: original product + original invoice + product certificate.
- Payment via RTGS/NEFT only, paid to the name on the invoice, within 5–10 days.
- Kisna may update/withdraw/change this policy without prior notice.
- Contact for exchange/buyback queries: ecom@kisna.com (distinct from general support@kisna.com).

## CERTIFICATION
- BIS Hallmark: certifies purity of gold and silver (BIS triangle logo, caratage/purity, assay centre logo, jeweller's code, hallmarking date code).
- IGI (International Gemological Institute): certifies diamonds/gemstones/jewellery.
- GIA and SGL also referenced as recognized diamond labs; HRD, GSI, NGTC available on request via franchise.
- Lost certificate: a duplicate can be issued for ₹500 — the original product is required for a quality check before reissuing.

## DIAMOND BUYING GUIDE — THE 4Cs
- Color: absence of color; colorless is most valuable. D–F colorless, G–J near-colorless, K–M faint hue.
- Cut: how well facets interact with light. Excellent > Good > Poor.
- Clarity: freedom from inclusions/blemishes. FL (Flawless), VS (Very Slightly Included), SI (Slightly Included).
- Carat: weight (1 carat = 200mg, divided into 100 points). 0.5ct delicate, 1ct classic, 2ct+ bold.
- Recommended buying process: define purpose (casual/occasional/ceremonial), define style/type, set a budget then pick diamond quality via the 4Cs, verify certifications (BIS for gold; GIA/SGL/IGI for diamonds).

## JEWELLERY CARE
- Minimize touching diamonds (skin oils dull them over time).
- Avoid hairspray, creams, and lotions — can discolor stones and reduce shine.
- Clean diamond jewellery: warm water + a few drops of mild unscented soap, soak ~30 min, dry with a clean cloth, soft-bristled toothbrush for residue.
- Clean gold jewellery: warm water + mild soap, soak 15–20 min, rinse cold, air-dry flat; soft brush for crevices (works for yellow/white/rose gold).
- Storage: store each piece separately (diamonds can scratch other jewellery), ideally fabric-lined box with compartments or wrapped in soft tissue.
- Avoid hot/cold water on gemstone pieces.

## PAYMENT
- Accepted: debit/credit cards, net banking, UPI/wallets (Google Pay, PhonePe, MobiKwik, PayZapp, Freecharge, Ola Money).
- Cash on Delivery (COD): NOT available — online payment only.
- EMI: available on checkout via major bank cards.
- Fraud prevention: payment partners monitor for suspicious activity; flagged transactions held for manual review; ID may be requested to confirm the cardholder.

## ORDERS
- Editing: you cannot add or edit a product once an order is placed. You can remove a product before it's packed/shipped via "My Orders" (cancel option).
- Multiple products: yes — add to cart and check out together.
- Duplicate order: contact +91 80651 55600 or support@kisna.com.
- Order confirmation: a confirmation page with a unique Order ID, item listing, shipping address, plus a confirmation email; tracking details on dispatch.
- Different shipping vs billing address: allowed.

## DELIVERY & SHIPPING
- Free shipping throughout India.
- Most orders dispatch within ~6 working days (delays possible around Sundays/public holidays).
- Tracking: an email with tracking number and courier name is sent once dispatched.
- Packaging: boxed with a plastic outer layer; each product individually bubble-wrapped.
- Report delivery issues immediately to support@kisna.com.
- Buy online, pick up in store: select "In-Store Delivery" at checkout and choose your store.

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

## STORE & IN-STORE SERVICES
- Store locator: kisna.com/store (searchable by city). Authorized dealers: kisna.com/kisna-authorized-dealers.
- In-store: jewellery consultation (no purchase obligation), try-on, servicing, exchange/buyback at any store.
- Online and in-store pricing/offers are uniform.

## SUPPORT & CONTACT
- Customer support phone: +91 80651 55600.
- Support hours: 10:00 am–6:30 pm IST Mon–Fri; 10:00 am–4:00 pm IST Sat.
- WhatsApp ("Chat with Experts"): +91 89768 74310.
- General support email: support@kisna.com.
- Exchange/buyback email: ecom@kisna.com.
- Corporate: corporate@kisna.com. HR/careers: hr@kisna.com.
- Head office: B-803, 8th Floor, The Capital, BKC, Bandra East, Mumbai 400051.
- Social: Instagram @kisnadiamondjewellery, Facebook KisnaDiamondJewellery, YouTube KisnaDiamondJewellery, Twitter/X @kisnaindia.

## FRANCHISE & CAREERS
- Franchise: 5-year exclusive agreement (2-year lock-in), store 800–2,000 sq ft. Kisna provides design/merchandising/marketing support, ops manual, staff training, billing software, POS.
- Franchise contact: franchise@kisna.com, +91-22-6716-0000, WhatsApp +91-91524-84423.
- Careers: apply on-page with CV; email hr@kisna.com.

## PROMOTIONS (time-sensitive — may change; do NOT quote as permanent)
- Recently advertised: up to 75% off diamond making charges, up to 50% off gold.
- For current live offers, always direct the customer to the View Offers menu rather than quoting these percentages.

## ACCOUNT
- Sign up at www.kisna.com with name, email, and a password.
- Forgot password: click "forgot password" under sign-in, enter registered email, receive a reset link.

## KISNA MERI ROSHNI (KMR) — Monthly Savings Plan — meriroshni.kisna.com
- KMR is Kisna's "10+1" monthly jewellery savings plan with two variants: KMR-Amount and KMR-Gram.
- How to join: visit any Kisna exclusive store (store staff will assist), or enroll online at meriroshni.kisna.com.
- Support phone: 8065155600.

### KYC Requirements
- Aadhaar Card or Passport required at store enrollment.
- PAN Card required if the monthly installment amount is ₹19,000 or above.
- PAN Card mandatory at redemption for any redemption value above ₹2,00,000 (per RBI guidelines).

### Installment Rules
- Minimum monthly installment: ₹2,000 (in multiples of ₹500). No maximum cap.
- Installment amount cannot be changed after the plan has started.
- Due date: same date each month as the first installment.
- No additional benefit for paying early or in advance.
- Confirmation: via email, SMS, and online passbook/dashboard.

### Payment Options
- Online: Credit card, Debit card, Net banking, UPI.
- In-store: cash, card, cheque, demand draft.
- Failed online payment: wait 48 hours; if not credited, contact support with payment screenshot.
- Subsequent installments can be paid at ANY Kisna exclusive store or on the website.

### KMR-Amount Plan
- Pay a fixed installment for 10 months. The 11th month's installment value is given by Kisna as a discount at redemption.
- Maturity benefit: Diamond jewellery 100% of 1st installment value; Gold jewellery 75% of 1st installment value.
- Example: ₹2,000/month × 10 months → ₹2,000 discount for diamond, or ₹1,500 for gold.

### KMR-Gram Plan (Gold Saving Scheme)
- Each monthly installment converts into 24KT gold grams at the live gold rate on payment date.
- Structure: 10 monthly deposits; bonus gram month credited at maturity.
- Maturity benefit: Diamond 100% of bonus month grams; Gold 75% of bonus month grams.

### Defaulting & Early Closure
- Defaulting any installment: maturity benefit forfeited; customer receives only principal at maturity.
- Early closure: principal only refunded to bank within 15 banking working days. No cash refunds.

### Pre-Maturity Redemption
- Eligible after more than 6 monthly installments paid.
- Pre-maturity benefit: Diamond 50% of 1st installment; Gold 37.5% of 1st installment.

### Redemption Rules
- Redeem at any Kisna exclusive store or kisna.com.
- Eligible: diamond jewellery and gold jewellery ONLY.
- NOT eligible: Gold Coins, Silver Coins, Rare Solitaire, Plain Platinum, Studded Diamond Platinum.
- Cannot split redemption across diamond and gold — one category per plan.
- Cash withdrawal instead of jewellery: NOT allowed.
"""