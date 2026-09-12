"""
KISNA Knowledge Base — single source of truth for the GeneralAgent (KIA).

Condensed from the official KISNA team knowledge base (June 2026).
All numbers are the resolved authoritative values. Do NOT approximate
or let the model round these — quote them exactly.

When this KB exceeds ~12k tokens, switch GeneralAgent from prompt-injection
injected into the GeneralAgent system prompt (no vector DB).

Two versions live here side by side:
  - KISNA_KNOWLEDGE_BASE     -- the original KB; kept only as the base
    template KISNA_KNOWLEDGE_BASE_V2 is built from (general_agent_kisna.py).
  - KISNA_KNOWLEDGE_BASE_V2  -- the client's September 2026 re-scrape, adopted
    verbatim EXCEPT the flagship-store count, which the client separately
    confirmed stays at "160+" (their new doc says "120+"; that single figure
    was overridden here, everything else in their doc is used as supplied).
    This is the live KB.
"""

KISNA_KNOWLEDGE_BASE = """\
# KISNA KNOWLEDGE BASE (authoritative source of truth)

## COMPANY
- Brand: KISNA (Diamond & Gold Jewellery), by Hari Krishna Group / Hari Krishna Exports Pvt. Ltd.
- Founded: 2005 (Kisna brand launched in Mumbai); Hari Krishna Group established 1992.
- Founder: Shri Savji Dholakia — Padma Shri awardee (2022).
- Headquartered in Mumbai, Maharashtra. (Never share the head/corporate office street address with customers - see rule below.)
- Footprint: 160+ flagship stores; 3,500+ retail touchpoints across 29 Indian states.
- Products: Diamond, gold, AND gemstone jewellery — rings, earrings, pendants, mangalsutras, bangles, bracelets, necklaces, nose pins, chains, and a 9KT gold line. KISNA DOES sell gemstone (ruby/emerald/sapphire etc.) jewellery. The ONLY materials KISNA does NOT sell are silver, platinum, and pearl.
- All natural diamonds set in 14KT/18KT gold; every piece is hallmarked.
- Sister brands: Kisna, Siva, RARE, Platinum, Oro, Rang.

## BRAND PROMISE
- Certified jewellery (BIS Hallmark for gold; IGI/GIA for diamonds).
- 7-day money-back guarantee.
- Free shipping within India.
- Easy exchange & buyback.
- Free jewellery insurance.
- Uniform pricing across website, app, and physical stores.

## RETURNS POLICY (authoritative)
- Return window: 7 days, no-questions-asked, from date of receipt.
- Eligibility: item must be unworn/unused, in original condition, with tags and original packaging, plus receipt/proof of purchase.
- How to return: the customer must REQUEST a return FIRST — contact support by phone (+91 81694 40000) or email (support@kisna.com). Kisna arranges pickup once approved. Items shipped back WITHOUT a prior request are NOT accepted.
- Damaged/wrong item: inspect on receipt and report immediately for evaluation.
- Exclusions: sale items and gift cards are NOT eligible for return.
- Refunds: if approved within the 7-day window, customer gets a 100% refund to the original payment method, processed within 10 business days (bank/card processing may add delay).
- Return/resizing/exchange shipping charge: there is NO standard flat fee for this — do not quote one (e.g. do not say "₹100" or any other amount). If a customer asks what it costs, say a support agent will confirm for their specific case (do not guess a number).
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
- EMI: NOT available directly at Kisna. Customer can pay via credit card from a major bank and, if their bank offers it, convert the transaction into EMI afterward — direct EMI-conversion queries to the customer's own bank support.
- Fraud prevention: payment partners monitor for suspicious activity; flagged transactions held for manual review; ID may be requested to confirm the cardholder.

## ORDERS
- Editing: you cannot add or edit a product once an order is placed. You can remove a product before it's packed/shipped via "My Orders" (cancel option).
- Multiple products: yes — add to cart and check out together.
- Duplicate order: contact +91 81694 40000 or support@kisna.com.
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
- Customer support phone: +91 81694 40000.
- Support hours: 10:00 am–6:30 pm IST Mon–Fri; 10:00 am–4:00 pm IST Sat.
- WhatsApp ("Chat with Experts"): +91 89768 74310.
- General support email: support@kisna.com.
- Exchange/buyback email: ecom@kisna.com.
- Corporate: corporate@kisna.com. HR/careers: hr@kisna.com.
- Head/corporate office: located in Mumbai. NEVER share the street address with customers; if asked, help them find their nearest STORE via the store locator instead.
- Social: Instagram @kisnadiamondjewellery, Facebook KisnaDiamondJewellery, YouTube KisnaDiamondJewellery, Twitter/X @kisnaindia.

## FRANCHISE & CAREERS
- Franchise: 5-year exclusive agreement (2-year lock-in), store 800–2,000 sq ft. Kisna provides design/merchandising/marketing support, ops manual, staff training, billing software, POS.
- Franchise contact: franchise@kisna.com, +91-22-6716-0000, WhatsApp +91-91524-84423.
- Careers: apply online at https://www.kisna.com/careers-and-job-opportunities (upload CV on the page), or email hr@kisna.com. The bot has NO list of open positions and cannot check application status or help with a specific role — only share the careers page + hr@kisna.com, then stop. Never imply you can assist further with jobs.

## PROMOTIONS (time-sensitive — may change; do NOT quote as permanent)
- Making-charge discounts run on a slab table by jewellery price, and the
  live table is built by the offers flow. NEVER quote a percentage here:
  the figures previously written on this line (75% diamond / 50% gold)
  had drifted from what the offers flow actually serves (up to 100%
  diamond), so the bot contradicted itself depending on which path
  answered. The offers flow is the single source of truth.
- For current live offers, always direct the customer to the View Offers menu rather than quoting these percentages.

## ACCOUNT
- Sign up at www.kisna.com with name, email, and a password.
- Forgot password: click "forgot password" under sign-in, enter registered email, receive a reset link.

## KISNA MERI ROSHNI (KMR) — Monthly Savings Plan — https://meriroshni.kisna.com/
- KMR is Kisna's "10+1" monthly jewellery savings plan with two variants: KMR-Amount and KMR-Gram.
- How to join: visit any Kisna exclusive store (store staff will assist), or enroll online at https://meriroshni.kisna.com/.
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

KISNA_KNOWLEDGE_BASE_V2 = """\n# KISNA KNOWLEDGE BASE (authoritative source of truth)

## COMPANY
- Brand: KISNA (Diamond & Gold Jewellery), by Hari Krishna Group / Hari Krishna Exports Pvt. Ltd.
- Founded: 2005 (Kisna brand launched in Mumbai); Hari Krishna Group established 1992.
- Founder: Shri Savji Dholakia — Padma Shri awardee (2022).
- Headquartered in Mumbai, Maharashtra. (Never share the head/corporate office street address with customers — see rule in SUPPORT & CONTACT.)
- Footprint: 160+ flagship stores; 3,500+ retail touchpoints across 29 Indian states; 8,000+ jewellery designs.
- Products online: Diamond, gold, gemstone (ruby/emerald/sapphire etc.), and solitaire jewellery — rings, earrings, pendants, mangalsutras, bangles, bracelets, necklaces, nose pins, chains, and a 9KT gold line.
- Products in select physical stores only (NOT available online): Platinum jewellery, silver coins. Gold coins and bars also available in stores.
- The ONLY material KISNA does NOT sell anywhere is pearl.
- All natural diamonds set in 14KT/18KT gold; every piece is hallmarked.
- Sister brands (under House of HK): Kisna, Siva, RARE, Platinum, Oro, Rang.

## BRAND PROMISE
- Certified jewellery (BIS Hallmark for gold; IGI/GIA for diamonds).
- 7-day money-back guarantee.
- Free shipping within India.
- Easy exchange & buyback.
- Free jewellery insurance.
- Uniform pricing across website, app, and physical stores.

## RETURNS POLICY (authoritative — /return-and-shipping-policy)
- Return window: 7 days, no-questions-asked, from date of receipt.
- Eligibility: item must be unworn/unused, in original condition, with tags and original packaging, plus receipt/proof of purchase.
- How to return: the customer must REQUEST a return FIRST — contact support by phone (+91 81694 40000) or email (support@kisna.com). Kisna arranges pickup once approved. Items shipped back WITHOUT a prior request are NOT accepted.
- Damaged/wrong item: inspect on receipt and report immediately for evaluation.
- Exclusions: sale items and gift cards are NOT eligible for return.
- Refunds: if approved within the 7-day window, customer gets a 100% refund to the original payment method, processed within 10 business days (bank/card processing may add delay).
- Return/resizing/exchange shipping charge: there is NO standard flat fee for this — do not quote one (e.g. do not say "₹100" or any other amount). If a customer asks what it costs, say a support agent will confirm for their specific case (do not guess a number).
- Partial returns: allowed per individual item, but each returned product must be returned in full, including all components.
- Ring doesn't fit: check the size guide before ordering; if it still doesn't fit, send it back for resizing/exchange.
- Track a return: via chat support or by emailing support@kisna.com.

## EXCHANGE POLICY (authoritative — /buyback-and-exchange-policy)
- Applies to products sold in India, available for the lifetime of the product, but only 7+ days after purchase date, subject to Quality Assurance review (item must be free of tampering, damage, alteration, or resizing — otherwise rejected).
- Diamond jewellery: 95% of current product price (excl. GST); labour charges NOT deducted; any original discounts/offers are deducted.
- Gold jewellery: 100% of current gold value.
- Required: original product + original invoice + product certificate (a missing diamond certificate incurs a charge).
- How exchange credit works: the exchange value is applied as an online redemption credit — it can ONLY be used for purchases on kisna.com and cannot be encashed or used in physical stores. (Note: There is no active "Kisna account" system — the credit is applied directly at checkout online.)
- Old gold (distinct from Kisna-jewellery exchange): can be exchanged at any physical Kisna store for 100% value, no deductions.

## BUYBACK POLICY (authoritative — /buyback-and-exchange-policy)
- Diamond jewellery: 90% of current product price (excl. GST); labour charges NOT deducted; discounts/offers deducted.
- Gold jewellery: 97% of current gold value.
- Required: original product + original invoice + product certificate.
- Payment via RTGS/NEFT only, paid to the name on the invoice, within 5–10 days.
- Kisna may update/withdraw/change this policy without prior notice.
- Contact for all exchange/buyback queries: support@kisna.com.

## CERTIFICATION
- BIS Hallmark: certifies purity of gold and silver (BIS triangle logo, caratage/purity, assay centre logo, jeweller's code, hallmarking date code). The principal certifying body for gold in India.
- IGI (International Gemological Institute): Kisna's primary diamond certification lab. Certifies diamonds, gemstones, and jewellery. World's first gemological lab to commit to carbon neutrality. Widely accepted across the jewellery industry.
- GIA and SGL: also referenced as recognized diamond labs on Kisna's buying guide.
- HRD, GSI, NGTC: available on request via House of HK / franchise channel.
- Lost certificate: a duplicate can be issued for ₹500 — the original product is required for a quality check before reissuing.

## DIAMOND BUYING GUIDE — THE 4Cs
- Color: absence of color; colorless is most valuable. D–F colorless, G–J near-colorless, K–M faint hue.
- Cut: how well facets interact with light. Excellent > Good > Poor. Most important factor for sparkle.
- Clarity: freedom from inclusions/blemishes. FL (Flawless), VS (Very Slightly Included), SI (Slightly Included).
- Carat: weight (1 carat = 200mg, divided into 100 points). 0.5ct delicate, 1ct classic, 2ct+ bold statement.
- Recommended buying process: (1) define purpose — casual/occasional/ceremonial; (2) define style/type; (3) set a budget, then pick diamond quality via the 4Cs; (4) verify certifications — BIS for gold, IGI/GIA/SGL for diamonds.

## JEWELLERY CARE
- Minimize touching diamonds — skin oils transfer to the stone and cause a dulling film over time.
- Avoid hairspray, creams, and lotions — can gradually discolour diamonds and reduce lustre. Diamonds repel water but grease/oils stick easily (applies to cut and uncut diamonds).
- Clean diamond jewellery: warm water + a few drops of mild unscented soap → soak ~30 min → dry with a clean cloth → soft-bristled toothbrush for residue.
- Clean gold jewellery: warm water + mild soap/dishwashing solution → soak 15–20 min → rinse cold water → air-dry flat on clean cloth. Soft-bristled brush for crevices. Works for yellow, white, and rose gold.
- Gemstone pieces: clean gently. Do NOT use hot or cold water. Instead of tap water, use sodium-free seltzer water or club soda — the carbonation lifts grime. A professional jeweller's cleaning solution also works.
- Storage: store each piece separately — diamonds can chip and scratch each other and other jewellery. Use a fabric-lined jewellery box with separate compartments or wrap each piece individually in soft tissue.

## PAYMENT
- Accepted: debit/credit cards, net banking, UPI/wallets (Google Pay, PhonePe, MobiKwik, PayZapp, Freecharge, Ola Money).
- Cash on Delivery (COD): NOT available — online payment only.
- EMI: NOT available directly at Kisna. Customer can pay via credit card from a major bank and, if their bank offers it, convert the transaction into EMI afterward — direct EMI-conversion queries to the customer's own bank support.
- Fraud prevention: payment partners monitor for suspicious activity; flagged transactions held for manual review; ID may be requested to confirm the cardholder.

## ORDERS
- Editing: you cannot add or edit a product once an order is placed. You can remove a product before it's packed/shipped via "My Orders" (cancel option).
- Multiple products: yes — add to cart and check out together.
- Duplicate order: contact +91 81694 40000 or support@kisna.com.
- Order confirmation: a confirmation page with a unique Order ID, item listing, shipping address, plus a confirmation email; tracking details sent on dispatch.
- Different shipping vs billing address: allowed.

## DELIVERY & SHIPPING
- Free shipping throughout India.
- Most orders dispatch within 4-5 days (or as specified on the product detail page). Committed shipping time is calculated in working hours/days. Occasional delays possible due to unforeseen circumstances.
- Tracking: an email with tracking number and courier name is sent once dispatched.
- Packaging: boxed with a plastic outer layer; each product individually bubble-wrapped.
- Shipment cannot be rerouted once dispatched.
- Report delivery issues immediately to support@kisna.com.
- Buy online, pick up in store: select "In-Store Delivery" at checkout and choose your store.

## GOLD RATE PROTECTION PLAN (GRP) — kisna.com/pages/gold-rate-protection
- Featured in the site navigation header as "NEW GOLD PROTECTION."
- Allows customers to lock the prevailing gold rate at the time of booking, protecting them from future gold price increases during the offer period.
- NOTE: Validity dates (Q3 below) are campaign-specific and will change each season. The bot should NOT quote the specific dates as permanent — always direct customers to the page for current dates.

### GRP — Full FAQ (verified from live site)
- Q: What is Kisna Gold Rate Protection Plan (GRP)?
  A: It allows you to lock the prevailing gold rate at the time of placing your order or booking, protecting you from any future increase in gold prices during the offer period.

- Q: Who is eligible for the Gold Rate Protection Scheme benefit?
  A: The benefit is available on all eligible orders, subject to applicable terms and conditions.

- Q: What is the validity of the Gold Rate Protection offer?
  A: Campaign-specific — dates change each season. Direct customers to kisna.com/pages/gold-rate-protection for current validity dates. (Current campaign example: lock rate 6th Aug–5th Nov 2026; redeem 7th Aug–10th Nov 2026.)

- Q: Is an advance payment required to avail GRP?
  A: Yes. A minimum advance payment of 25% of the total order value is mandatory at the time of booking. Without the advance, the order will not be confirmed under GRP.

- Q: Can I purchase jewellery worth more than my advance payment?
  A: Yes. The advance amount can be applied toward purchases worth up to 4x the advance paid.

- Q: Can I use the GRP benefit multiple times?
  A: No. GRP can be availed only once per order. It cannot be transferred, reused, or combined across multiple transactions.

- Q: Which categories are COVERED under GRP?
  A: Gold Jewellery, Diamond Jewellery, Platinum Jewellery, and Solitaire Jewellery.

- Q: Which categories are NOT covered under GRP?
  A: Gold coins, silver coins, and bars are excluded.

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
- Rate note: SafeGold price reflects real-time commodity/market rates. Kisna's e-commerce gold price is higher because it includes manufacturing, processing, and operational costs. SafeGold prices fluctuate throughout the day.

### Buying
- Cheque payments (including post-dated cheques): NOT accepted — fully digital product only.
- Order cancellation: NOT possible once a digital gold purchase order is placed.
- Invoice: downloadable directly from the platform.
- Holding statement: always available on the platform.

### Storage & Safety
- Gold is stored with Brink's (global precious metal vaulting leader). Fully insured during storage and transit.
- Administrator: Vistra Corporate Services (India) Private Limited — holds a charge over all stored gold, ensuring customer gold is protected and segregated regardless of DGIPL's operational status.
- Storage duration: up to 10 years from purchase date. Free for the first 5 years; a nominal custody fee applies after 5 years (customer notified before any charge; option to sell or request delivery).
- If DGIPL goes into liquidation: customer holdings are legally separate from DGIPL's corporate assets. Physical gold is NOT treated as DGIPL's asset. Redemption dispatched via reputable logistics provider upon request.

### Selling
- Can sell any portion of holdings at the live sell rate. Minimum sell: ₹100, up to total gold owned.

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
- Customer support phone: +91 81694 40000.
- Support hours: 10:00 am–6:30 pm IST Mon–Fri; 10:00 am–4:00 pm IST Sat.
- WhatsApp ("Chat with Experts"): +91 89768 74310.
- Support email: support@kisna.com — use this for ALL queries (general, returns, order status, exchange/buyback). This is the ONLY active customer email. Any previous separate transactional email address has been decommissioned.
- Corporate enquiries: corporate@kisna.com. HR/careers: hr@kisna.com.
- Grievance: kisna.com/privacy-policy (Grievance section).
- Head/corporate office: located in Mumbai. NEVER share the street address with customers; if asked, help them find their nearest STORE via the store locator instead.
- Social: Instagram @kisnadiamondjewellery, Facebook KisnaDiamondJewellery, YouTube KisnaDiamondJewellery, Twitter/X @kisnaindia, Pinterest kisnaindia, LinkedIn kisna-diamond-jewellery.

## FRANCHISE & CAREERS
- Franchise: 5-year exclusive agreement (2-year lock-in), store 800–2,000 sq ft. Kisna provides location selection support, store design/layout, merchandising (incl. exchange for non-moving stock), national/regional marketing, ops manual, staff training, billing software, POS material.
- Franchise contact: franchise@kisna.com, +91-22-6716-0000, WhatsApp +91-91524-84423.
- Careers: apply online at https://www.kisna.com/careers-and-job-opportunities (fill form + upload CV), or email hr@kisna.com. The bot has NO list of open positions and cannot check application status — only share the careers page + hr@kisna.com, then stop. Never imply you can assist further with jobs.

## PROMOTIONS (time-sensitive — may change; do NOT quote as permanent)
- Making-charge discounts run on a slab table by jewellery price, and the live table is built by the offers flow. NEVER quote a specific percentage: the figures drift and the bot will contradict itself depending on which path answered. The offers flow is the single source of truth.
- For current live offers, always direct the customer to the View Offers menu rather than quoting percentages.
- Time-limited discount/coupon codes (first-order, festive, category-specific, etc.) may exist and change frequently. NEVER state that no such code exists or that Kisna "doesn't offer" one -- that is not a fact this KB has. Point the customer to the View Offers menu, or to a live representative for a code check.

## ACCOUNT
- Sign up at www.kisna.com with name, email, and a password.
- Forgot password: click "forgot password" under sign-in, enter registered email, receive a reset link.

## KISNA MERI ROSHNI (KMR) — Monthly Savings Plan — https://meriroshni.kisna.com/
- KMR is Kisna's "10+1" monthly jewellery savings plan with two variants: KMR-Amount and KMR-Gram.
- How to join: visit any Kisna exclusive store (store staff will assist), or enroll online at https://meriroshni.kisna.com/.
- KMR support phone: 8065155600.

### KYC Requirements
- Aadhaar Card or Passport required at store enrollment.
- PAN Card required if the monthly installment amount is ₹19,000 or above.
- PAN Card mandatory at redemption for any redemption value above ₹2,00,000 (per RBI guidelines).

### Installment Rules
- Minimum monthly installment: ₹2,000 (in multiples of ₹500 — e.g. ₹2,000 / ₹2,500 / ₹3,000). No maximum cap.
- Installment amount CANNOT be changed after the plan has started.
- Due date: same date each month as the first installment (e.g. 1st Jan → 1st Feb → 1st Mar).
- No additional benefit for paying early or in advance.
- Confirmation: via email, SMS, and online passbook/dashboard (shows payments, status, installments paid, due dates).

### Payment Options
- Online: Credit card, Debit card, Net banking, UPI.
- In-store (at any Kisna exclusive store): cash, card, cheque, demand draft.
- Failed online payment: wait 48 hours (payment gateway server issues may auto-resolve). If still not credited after 48 hours, contact support with payment screenshot.
- Subsequent installments can be paid at ANY Kisna exclusive store or on the website — not locked to enrollment location.

### KMR-Amount Plan
- Pay a fixed installment for 10 months. The 11th month's installment value is given by Kisna as a discount at redemption.
- Maturity benefit:
  - Diamond jewellery: 100% discount equivalent to 1st installment value.
  - Gold jewellery: 75% discount equivalent to 1st installment value.
- Example: ₹2,000/month × 10 months → Kisna gives ₹2,000 discount on diamond jewellery, or ₹1,500 on gold jewellery.
- Ongoing Kisna promotions/offers can be combined at maturity or pre-maturity redemption.

### KMR-Gram Plan (Gold Saving Scheme)
- Each monthly installment converts into 24KT gold grams at the live gold rate on the payment date (provides price protection if gold prices rise later).
- Structure: 10 monthly deposits; 1 bonus gram month credited at maturity.
- Maturity benefit:
  - Diamond jewellery: 100% of the bonus month's gold gram value.
  - Gold jewellery: 75% of the bonus month's gold gram value.
- At redemption: all accumulated grams are converted at the current gold rate on the redemption date.
- Example (₹10,000/month at varying monthly rates): 10 months = 11.635g accumulated → at ₹10,940/gram on redemption day → ₹1,27,287 redeemable value. Diamond bonus: +0.914g; Gold bonus: +0.686g.

### Defaulting & Early Closure
- Defaulting any installment: the maturity benefit is forfeited. Customer receives back only the total paid principal at maturity.
- Early closure (anytime before maturity): can withdraw paid installments. Gets back principal only, no benefit. Refund remitted to bank account within 15 banking working days. Cash refunds NOT given.

### Pre-Maturity Redemption
- Eligible after paying MORE THAN 6 monthly installments (not yet at full maturity).
- Pre-maturity benefit:
  - Diamond jewellery: 50% of the 1st installment value as discount (e.g. ₹2,000/month → ₹1,000 discount).
  - Gold jewellery: 37.5% of the 1st installment value as discount (e.g. ₹2,000/month → ₹750 discount).
- NOTE: The Kisna website's General FAQ section shows examples at half these values (₹500 / ₹375) — that is an error on Kisna's site. The correct values above are confirmed by the Gold Saving Scheme FAQ section on the same page. Use the values above.

### Redemption Rules
- Where to redeem: any Kisna exclusive store or kisna.com — NOT restricted to enrollment store.
- Eligible products: diamond jewellery and gold jewellery ONLY.
- NOT eligible for redemption: Gold Coins, Silver Coins, Rare Solitaire, Plain Platinum jewellery, Studded Diamond Platinum jewellery.
- Cannot split one plan across diamond and gold — must choose ONE category per plan at redemption.
- If invoice value > plan value: customer pays the difference. No refunds, carry-forward credit notes, or advance vouchers issued.
- Combining plans: two plans can be combined for family members with written consent of plan holders; billing invoice in one holder's name.
- Third-party redemption: friend or relative can redeem on behalf of customer by completing mandatory processes.
- Non-redemption after maturity: Kisna waits up to 365 days from the 1st installment date, then refunds the full paid principal (no benefit) to bank account.
- Cash withdrawal instead of jewellery: NOT allowed under any circumstances.
"""
