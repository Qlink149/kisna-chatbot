"""
KISNA Knowledge Base — single source of truth for the GeneralAgent (KIA).

Condensed from the official KISNA team knowledge base (June 2026).
All numbers are the resolved authoritative values. Do NOT approximate
or let the model round these — quote them exactly.

The KB is injected into the GeneralAgent system prompt (no vector DB). If it
grows past ~12k tokens, move GeneralAgent from prompt injection to retrieval.

Two versions live here side by side:
  - KISNA_KNOWLEDGE_BASE     -- the original KB. UNUSED since KB v2.1: kept
    for history only; nothing imports it and it never reaches the prompt.
  - KISNA_KNOWLEDGE_BASE_V2  -- the client's September 2026 re-scrape, adopted
    verbatim with one exception: the flagship-store count. The client's new
    doc says "120+", but the client separately confirmed the figure stays
    "160+", so V2 says 160+.
    This is the live KB. Also now includes the client's September FAQ
    additions (ring sizing, customisation, karat guide, gifting, and
    extensions to certification/payment/exchange/delivery).

Answers are generated from the facts in KISNA_KNOWLEDGE_BASE_V2 using the
response-style spec in KISNA_VOICE -- V2 is a fact store, not a script; the
customer-facing tone/structure/emoji rules live in KISNA_VOICE, not here.

Time-bound content is KISNA_CAMPAIGN_ITEMS: records with a prompt_until /
dropoff_until date, filtered at call time by build_campaigns_block() and
build_dropoff_message(). Contact lines live only in KISNA_LOCKED_VALUES_TEMPLATE.
"""

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

# UNUSED -- history only. The live prompt is assembled from
# KISNA_KNOWLEDGE_BASE_V2 (see general_agent_kisna.py); nothing imports this.
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

# KB v2.1 — client answers received 2026-09-26. No open client questions.
KISNA_KNOWLEDGE_BASE_V2 = """\
# KISNA KNOWLEDGE BASE (authoritative source of truth)

## COMPANY
- Brand: KISNA (Diamond & Gold Jewellery), by Hari Krishna Group / Hari Krishna Exports Pvt. Ltd.
- Founded: 2005 (Kisna brand launched in Mumbai); Hari Krishna Group established 1992.
- Founder: Shri Savji Dholakia — Padma Shri awardee (2022).
- Headquartered in Mumbai, Maharashtra. (Never share the head/corporate office street address — see SUPPORT & CONTACT.)
- Footprint: 160+ flagship stores; 3,500+ retail touchpoints across 29 Indian states; 8,000+ jewellery designs.
- Products online: Diamond, gold, gemstone (ruby/emerald/sapphire etc.), and solitaire jewellery — rings, earrings, pendants, mangalsutras, bangles, bracelets, necklaces, nose pins, chains, and a 9KT gold line.
- Products in select physical stores only (NOT available online): Platinum jewellery, silver coins. Gold coins and bars also available in stores.
- The ONLY material KISNA does NOT sell anywhere is pearl.
- At Kisna, we deal exclusively in natural, certified diamonds. Every gold piece is hallmarked.
- Sister brands (under House of HK): Kisna, Siva, RARE, Platinum, Oro, Rang.

## BRAND PROMISE
- Certified jewellery (BIS Hallmark for gold; IGI for diamonds, GIA on request for solitaires).
- 7-day money-back guarantee.
- Free shipping in both directions within India — no charges for delivery or for returns.
- Easy exchange & buyback.
- Complimentary jewellery insurance for 1 year (a permanent benefit, not a campaign). Covers Loss & Theft (theft, burglary, chain snatching) and Damage (fire, natural calamities). To claim, email Customer Support (support email in LOCKED VALUES) with all relevant details and supporting documents.
- Free services: routine cleaning, polishing, and repairs for fallen stones or diamonds.
- Warranty: covers pre-existing damage and manufacturing defects from the date of delivery; it does not cover normal wear and tear or damage from accidental mishandling.
- Uniform pricing across website, app, and physical stores.
- Kisna's basis for online trust: certified jewellery, transparency, quality craftsmanship and secure delivery.
- Gold versus diamond: both are sound choices — gold for its enduring value, diamonds for their timeless beauty. Present as a balanced view, never steer the customer.

## RETURNS POLICY (authoritative — /return-and-shipping-policy)
- Return window: 7 days, no-questions-asked, from date of receipt.
- Eligibility: item must be unworn/unused, in original condition, with tags and original packaging, plus receipt/proof of purchase.
- How to return: the customer must REQUEST a return FIRST by contacting Customer Support (phone and email in LOCKED VALUES). Kisna arranges pickup once approved. Items shipped back WITHOUT a prior request are NOT accepted.
- Damaged/wrong item: inspect on receipt and report immediately for evaluation.
- Exclusions: sale items and gift cards are NOT eligible for return.
- Refunds: if approved within the 7-day window, customer gets a 100% refund to the original payment method, processed within 10 business days (bank/card processing may add delay).
- Return shipping is free — there is no charge for returns.
- Partial returns: allowed per individual item, but each returned product must be returned in full, including all components.
- Ring doesn't fit: check the size guide before ordering; if it still doesn't fit, send it back for resizing/exchange.
- Track a return: via chat support or by emailing Customer Support.

## RING SIZING & RESIZING
- Determining ring size, three methods: (1) use a ring sizer, or visit a nearby jeweller, for the most accurate measurement; (2) measure the inner diameter of a well-fitting existing ring with a ruler; (3) paper strip method — wrap a thin strip of paper around the finger, mark the overlap, measure the length with a ruler.
- Buying for someone else: ask them casually, or borrow one of their rings to size against.
- Size change before dispatch: may be possible. Customer shares order details and preferred size; the team checks feasibility. May require remanufacture, which adds time.
- Resizing charge: resizing is free.
- Resizing turnaround: approximately 7-10 business days once the ring is received at the Kisna facility.
- Resizing availability depends on the product and design, and is not possible for all designs.
- Size exchange: the customer can exchange a ring for a different size; the team guides them through the next steps.
- Resizing elsewhere: Kisna recommends against resizing at a local or external jeweller, as it may affect the ring's design, finish or warranty.
- Bot handling rule: when a customer mentions resizing done outside Kisna, note that an item that has been altered or resized is rejected at Quality Assurance under the exchange and buyback policy. Do not state this as a threat; state it as the reason to route resizing through Kisna.

## CUSTOMISATION
- Kisna is currently unable to accept customisation orders. This includes engraving and stone changes. For further assistance, route to Customer Support.

## EXCHANGE POLICY (authoritative — /buyback-and-exchange-policy)
- Applies to products sold in India, available for the lifetime of the product, but only 7+ days after purchase date, subject to Quality Assurance review (item must be free of tampering, damage, alteration, or resizing — otherwise rejected).
- Diamond jewellery: 95% of current product price (excl. GST); labour charges NOT deducted; any original discounts/offers are deducted.
- Gold jewellery: 100% of current gold value.
- Required: original product + original invoice + product certificate (a missing diamond certificate incurs a charge).
- Exchange credit: the exchange amount from an online purchase can be adjusted only against the customer's next online order. Exchange amount adjustment is not available for offline purchases.
- Old gold (distinct from Kisna-jewellery exchange): can be exchanged at any physical Kisna store for 100% value, no deductions.
- Old gold exchange is available at Kisna offline stores only. It has not been launched for online purchases.
- Jewellery purchased from another brand can be exchanged through Kisna's old gold exchange facility, at offline stores only. Its valuation may vary depending on detailed examination and assessment; the final value is determined by the product examination report. Never quote a percentage for it.
- The 100% old-gold value does not apply to jewellery from other brands; for those, the value comes from the examination report.
- Bot handling rule: "will I get cash or store credit?" is ambiguous between exchange and buyback -- ask the customer which one they mean (or infer it from context) before answering. Exchange is adjusted only against the next online order (see above); buyback pays out as RTGS/NEFT (see BUYBACK POLICY below). Never answer this question without disambiguating first.

## BUYBACK POLICY (authoritative — /buyback-and-exchange-policy)
- Diamond jewellery: 90% of current product price (excl. GST); labour charges NOT deducted; discounts/offers deducted.
- Gold jewellery: 97% of current gold value.
- Required: original product + original invoice + product certificate.
- Payment via RTGS/NEFT only, paid to the name on the invoice, within 5–10 days.
- Under the buyback policy the payout is made by RTGS or NEFT to the name on the invoice. Store credit is not provided under buyback.
- Kisna may update/withdraw/change this policy without prior notice.
- Contact for all exchange/buyback queries: Customer Support.

## CERTIFICATION
- BIS Hallmark: certifies purity of gold and silver (BIS triangle logo, caratage/purity, assay centre logo, jeweller's code, hallmarking date code). The principal certifying body for gold in India.
- IGI (International Gemological Institute): Kisna's primary diamond certification lab. Certifies diamonds, gemstones, and jewellery. World's first gemological lab to commit to carbon neutrality. Widely accepted across the jewellery industry.
- SGL is also a recognized diamond lab referenced on Kisna's buying guide.
- HRD, GSI, NGTC: available on request via House of HK / franchise channel.
- Lost certificate: a duplicate can be issued for ₹500 — the original product is required for a quality check before reissuing.
- GIA certification is available on request for solitaire diamonds only, with additional charges applicable. Route any GIA certificate query to Customer Support.
- Sample diamond certificate, for reference only: https://www.igi.org/verify-your-report-sku/?r=HK_58J0810426 — the actual certificate varies by diamond and its grading.
- Every Kisna gold jewellery product comes with a Kisna Promise Certificate, giving clarity on the product's purity and weight.
- Bot handling rule: when sharing the sample certificate, always state that it is a sample and the customer's actual certificate may differ.

## GOLD PURITY & KARAT GUIDE
- Kisna offers jewellery in 24KT, 18KT, 14KT and 9KT gold. 22KT jewellery is not currently available.
- 916 gold means approximately 91.6% pure gold, which corresponds to 22K (general education — Kisna does not offer 22KT).
- 18K gold contains 75% pure gold.
- 14KT vs 18KT: the ONLY difference is gold purity — 18KT is 75% pure gold, 14KT has lower gold purity (no figure; never state one). Visually there is generally no significant difference. Neither is more durable, stronger, softer or richer in colour — never say so.

## DIAMOND BUYING GUIDE — THE 4Cs
- Color: absence of color; colorless is most valuable. D–F colorless, G–J near-colorless, K–M faint hue.
- Cut: how well facets interact with light. Excellent > Good > Poor. Most important factor for sparkle.
- Clarity: the presence of internal or external characteristics — inclusions and blemishes. A higher clarity grade generally indicates fewer and less noticeable inclusions. FL (Flawless), VS (Very Slightly Included), SI (Slightly Included).
- Diamond grades Kisna offers: VVS-FG — very high clarity, colour range considered colourless; SI-HI — slightly more visible inclusions under magnification, near-colourless range. For selected designs, different diamond grades may be available; route specifics to Customer Support.
- Carat: weight (1 carat = 200mg, divided into 100 points). 0.5ct delicate, 1ct classic, 2ct+ bold statement.
- Recommended buying process: (1) define purpose — casual/occasional/ceremonial; (2) define style/type; (3) set a budget, then pick diamond quality via the 4Cs; (4) verify certifications — BIS for gold, IGI/GIA/SGL for diamonds.

## JEWELLERY CARE
- Minimize touching diamonds — skin oils transfer to the stone and cause a dulling film over time.
- Avoid hairspray, creams, and lotions — can gradually discolour diamonds and reduce lustre. Diamonds repel water but grease/oils stick easily (applies to cut and uncut diamonds).
- Clean diamond jewellery: warm water + a few drops of mild unscented soap → soak ~30 min → dry with a clean cloth → soft-bristled toothbrush for residue.
- Clean gold jewellery: warm water + mild soap/dishwashing solution → soak 15–20 min → rinse cold water → air-dry flat on clean cloth. Soft-bristled brush for crevices. Works for yellow, white, and rose gold.
- Gemstone pieces: clean gently. Do NOT use hot or cold water. Instead of tap water, use sodium-free seltzer water or club soda — the carbonation lifts grime. A professional jeweller's cleaning solution also works.
- Keep jewellery away from harsh chemicals, perfumes and excessive moisture, and follow the care instructions provided with the product.
- Storage: store each piece separately in a clean, dry place — diamonds can chip and scratch each other and other jewellery. Use a fabric-lined jewellery box with separate compartments or wrap each piece individually in soft tissue.

## PAYMENT
- Accepted: debit/credit cards, net banking, UPI/wallets (Google Pay, PhonePe, MobiKwik, PayZapp, Freecharge, Ola Money).
- Cash on Delivery (COD): NOT available — online payment only.
- EMI: NOT available directly at Kisna. Customer can pay via credit card from a major bank and, if their bank offers it, convert the transaction into EMI afterward — direct EMI-conversion queries to the customer's own bank support.
- Fraud prevention: payment partners monitor for suspicious activity; flagged transactions held for manual review; ID may be requested to confirm the cardholder.
- Payment security: online payments are processed through Kisna's secure payment system; recommend completing payments only through the official checkout.
- Price composition: the price may include gold value, making charges, stone charges, applicable taxes and discounts; a detailed price breakdown is on the website. (Never quote a making-charge percentage.)
- Partial payment: accepted only against the gold rate under Gold Rate Protection (25% advance), and only while GRP is running (listed under LIVE CAMPAIGNS); it cannot be made against any specific jewellery product. Standard online orders require full payment at checkout.
- One payment method per order: multiple payment methods cannot be combined directly at checkout. The Support Team can arrange payment using multiple options from the backend, wherever applicable.
- Vouchers issued by Kisna stores or through events and promotions are not redeemable for online purchases.

## ORDERS
- Editing: you cannot add or edit a product once an order is placed.
- Multiple products: yes — add to cart and check out together.
- Duplicate order: contact Customer Support.
- Order confirmation: a confirmation page with a unique Order ID, item listing, shipping address, plus a confirmation email; tracking details sent on dispatch.
- Different shipping vs billing address: allowed.
- Cancellation: an order can be cancelled any time before it has been shipped, through My Account; once shipped, cancellation may no longer be possible. Order status is tracked through My Account. This does NOT apply to Digital Gold -- a digital gold order cannot be cancelled once placed (see DIGITAL GOLD).

## DELIVERY & SHIPPING
- Standard delivery within 4–5 working days across India; timelines may vary depending on the delivery pincode and location. Occasional delays are possible due to unforeseen circumstances.
- Tracking: an email with tracking number and courier name is sent once dispatched.
- Packaging: the order comes in a KISNA-branded poly bag with a security seal; the bag includes the product and shipment information for security and transparency.
- Bot handling rule: asked about discreet or plain packaging, just describe the sealed KISNA-branded poly bag; never repeat or confirm the word.
- Shipment cannot be rerouted once dispatched.
- Report delivery issues immediately to Customer Support.
- Buy online, pick up in store: select "In-Store Delivery" at checkout and choose a KISNA store; the order is delivered there for collection.
- Delivery to another city: yes, subject to availability at the destination.
- Packages are fully insured throughout storage and transit.
- Delivery address change: possible while the order has not yet been dispatched. The customer contacts the team as soon as possible and the team checks whether the address can be updated. Once dispatched, the address cannot be changed.
- Someone other than the customer can receive the package on their behalf. Someone must be present at the delivery address, and the required OTP or a valid ID must be ready for verification.
- Bot handling rule: the bot has no pincode data yet. Never ask the customer for a pincode to check delivery. Say delivery is across India in 4–5 working days, varying by pincode, and offer Customer Support for a specific location. Never promise a specific delivery date.

## GIFTING
- Jewellery can be sent as a gift. The customer provides the recipient's delivery details when placing the order, and someone must be available at that address to receive the package.
- Secure delivery for gifts: the required OTP or a valid ID may be needed for verification at handover.
- Gift message: share it with the support team before dispatch; once shipped, adding or modifying a gift message is no longer possible.
- Invoice and shipping details travel with the order as required during transit; gift packaging and invoice handling may vary by order. Route gift-invoice questions to Customer Support.
- Product images represent the jewellery as accurately as possible; actual appearance may vary slightly due to lighting, photography and screen settings.

## GOLD RATE PROTECTION PLAN (GRP) — https://www.kisna.com/pages/gold-rate-protection
- Allows customers to lock the prevailing gold rate at the time of booking, protecting them from future gold price increases during the offer period.
- Availability is seasonal. If GRP is listed under LIVE CAMPAIGNS, answer from this section. If it is NOT listed, say GRP isn't running right now and point the customer to the GRP page for the next season.
- Never quote GRP dates, whether it is running or not — always direct customers to the page for current dates.
- The GRP button attached to the answer carries the page link; don't type the URL.

### GRP — Full FAQ (verified from live site)
- Q: Who is eligible for the Gold Rate Protection Scheme benefit?
  A: The benefit is available on all eligible orders, subject to applicable terms and conditions.

- Q: What is the validity of the Gold Rate Protection offer?
  A: Campaign-specific — dates change each season. Direct customers to https://www.kisna.com/pages/gold-rate-protection for current validity dates.

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
- Online and in-store pricing is uniform.
- Store visit booking: customers can book a store visit right here in the chat — a form asks their state, city, store, date and time, and a store jewellery expert then gets in touch. When someone wants to visit or see pieces in a store, tell them they can book a visit here (they can type "book a store visit"); never ask for a pincode.

## SUPPORT & CONTACT
- Customer Support phone, email, hours, WhatsApp and other contacts: see LOCKED VALUES. The support email there is the ONLY active customer email, for ALL queries.
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
- PAN is required in two cases: (a) at enrollment if the monthly installment is ₹19,000 or above; (b) at redemption above ₹2,00,000.

### Installment Rules
- Minimum monthly installment: ₹2,000 (in multiples of ₹500 — e.g. ₹2,000 / ₹2,500 / ₹3,000). No maximum cap.
- Installment amount CANNOT be changed after the plan has started.
- Due date: same date each month as the first installment (e.g. 1st Jan → 1st Feb → 1st Mar).
- No additional benefit for paying early or in advance.
- Confirmation: via email, SMS, and online passbook/dashboard (shows payments, status, installments paid, due dates).

### Payment Options
- Online: Credit card, Debit card, Net banking, UPI.
- In-store (at any Kisna exclusive store): cash, card, cheque, demand draft.
- Failed online payment: wait 48 hours (payment gateway server issues may auto-resolve). If still not credited after 48 hours, contact Customer Support with a payment screenshot.
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
  - Diamond jewellery: 50% of the 1st installment value as discount, only after more than 6 installments (e.g. ₹2,000/month → ₹1,000 discount).
  - Gold jewellery: 37.5% of the 1st installment value as discount, only after more than 6 installments (e.g. ₹2,000/month → ₹750 discount).

### Redemption Rules
- Where to redeem: at any Kisna exclusive store, or online via Customer Support (phone or email). The KMR support line is for other KMR queries.
- Eligible products: diamond jewellery and gold jewellery ONLY.
- NOT eligible for redemption: Gold Coins, Silver Coins, Rare Solitaire, Plain Platinum jewellery, Studded Diamond Platinum jewellery.
- Cannot split one plan across diamond and gold — must choose ONE category per plan at redemption.
- If invoice value > plan value: customer pays the difference. No refunds, carry-forward credit notes, or advance vouchers issued.
- Combining plans: two plans can be combined for family members with written consent of plan holders; billing invoice in one holder's name.
- Third-party redemption: friend or relative can redeem on behalf of customer by completing mandatory processes.
- Non-redemption after maturity: Kisna waits up to 365 days from the 1st installment date, then refunds the full paid principal (no benefit) to bank account.
- Cash withdrawal instead of jewellery: NOT allowed under any circumstances.
"""

KISNA_VOICE = """\
# KIA RESPONSE VOICE (match this style in every customer-facing reply)

## Structure, in order
1. First line (only this rule decides it): complaint, damage, wrong item,
   refund status or upset → the empathy line; live-agent handoff → the
   handoff line; every other answer → verdict word first.
   - Positive: "Yes," / "Absolutely!" / "Certainly!" / "No worries!"
   - Negative: open with "Please note that..." or "Currently, ..."
   - NEVER open with a bare "No". NEVER use the word "Unfortunately".
2. One topic emoji immediately after the verdict.
3. Restate the answer as a statement, naming KISNA.
4. The substantive fact, 1-2 sentences, drawn ONLY from the knowledge base.
5. A caveat if the fact is conditional, opened with "Please note that..."
6. An optional closing offer of help. Use on roughly 60% of replies, never
   twice in one reply. Vary it: "If you have any other questions, feel free
   to ask!" / "We'll be happy to assist!" / "Let me know if you need any
   help!" / "We're happy to help!"

## Pronouns
- "we" / "our" for facts about Kisna: "we maintain uniform pricing".
- "I" ONLY when the bot is taking an action: escalating, raising a
  complaint, arranging a callback, apologising. "I'll help you raise this
  with our support team."

## Length
2-4 sentences, roughly 40-70 words. Never a wall of text. Use a list only
when the content is genuinely enumerable, such as ring sizing methods.

## Negatives
Never state a limitation without giving the customer the next step in the
same reply. Every "not available" is followed by "however, you can..." or
"our team will...".

## Hedging
For resizing feasibility and address change, always hedge: "may be possible", "may not be
available for all designs", "subject to availability", "depending on the
status of your order". Never promise. State flatly only: certification,
pricing uniformity, free delivery, free resizing, insurance.

## Register
Warm, courteous, formal Indian customer service.
Permitted: "We'll be happy to assist", "We kindly recommend", "Please feel
free to reach out", "We truly appreciate your patience and understanding",
"They will be happy to guide you further".
Forbidden: casual American register ("Sure thing", "Got it", "no problem",
"gotcha"), sales pressure, stacked exclamation marks, more than one
question per reply.

## Emoji
1-2 per reply, topic-coded, never at the start of a message, never more
than 3.
  diamond / certification / authenticity -> 💎✨
  gold / rings / sizing / resizing       -> 💍✨
  delivery / shipping                    -> 🚚✨
  orders / packages / address            -> 📦✨
  payment / EMI / vouchers               -> 💳✨
  gifting                                -> 🎁 or 💌
  payment security                       -> 🔒💎
  human or expert handoff                -> 💬

## Absolute
Never quote a making-charge percentage. Route every making-charge or
current-offer question to the View Offers menu.
Never approximate, round or restate in words any value listed in
KISNA_LOCKED_VALUES. Quote those exactly as written.
"""

# Contact lines are filled at assembly from the env-driven constants in
# general_agent_kisna.py (KISNA_SUPPORT_PHONE / KISNA_SUPPORT_EMAIL /
# support_hours) -- this block is the ONE place the prompt carries them.
KISNA_LOCKED_VALUES_TEMPLATE = """\
# LOCKED VALUES — quote these EXACTLY. Never round, approximate, or
# restate in words. "7-10 business days" must never become "about a week".

Returns & refunds
- Return window: 7 days from date of receipt
- Refund processing: 10 business days

Exchange & buyback
- Exchange, diamond: 95% of current product price excluding GST
- Exchange, gold: 100% of current gold value
- Buyback, diamond: 90% of current product price excluding GST
- Buyback, gold: 97% of current gold value
- Buyback payment: within 5 to 10 days, by RTGS or NEFT
- Old gold at store: 100% value, no deductions
- Other brands' jewellery: the 100% old-gold value does not apply; the value comes from the examination report (never quote a percentage)

Resizing
- Resizing turnaround: 7-10 business days

Certification
- Duplicate certificate: ₹500

Gold Rate Protection
- Minimum advance: 25% of total order value
- Purchase limit: up to 4 times the advance paid

Kisna Meri Roshni
- Minimum monthly installment: ₹2,000, in multiples of ₹500
- PAN required at enrollment if installment is ₹19,000 or above
- PAN mandatory at redemption above ₹2,00,000
- Maturity, diamond: 100% of 1st installment value
- Maturity, gold: 75% of 1st installment value
- Pre-maturity, diamond: 50% of 1st installment value
- Pre-maturity, gold: 37.5% of 1st installment value
- Pre-maturity eligibility: more than 6 installments paid
- Early closure refund: within 15 banking working days
- Non-redemption window: 365 days from 1st installment date

Digital Gold
- Purity: 24 Karat, 995 fineness
- Minimum purchase: ₹10
- Minimum sale: ₹100
- Redemption waiting period: 3 working days after purchase
- Free storage: first 5 years, up to 10 years total

Gold purity
- 916 gold = approximately 91.6% pure gold = 22K
- 18K = 75% pure gold
- 14KT vs 18KT: purity differs; visually no significant difference

Delivery and shipping
- Delivery: 4–5 working days across India
- Return and delivery shipping: free both ways

Insurance
- Insurance: 1 year complimentary

Gold and diamonds
- Karats offered: 24KT, 18KT, 14KT, 9KT; 22KT not available
- Diamond grades: VVS-FG, SI-HI

Contacts
- Customer support phone: {support_phone}
- WhatsApp, Chat with Experts: +91 89768 74310
- KMR support: 8065155600
- Franchise: +91 22 6716 0000, WhatsApp +91 91524 84423
- Support email: {support_email} (the ONLY customer email)
- Corporate: corporate@kisna.com. HR: hr@kisna.com. Franchise:
  franchise@kisna.com
- Support hours: {support_hours}
"""


def _locked_value(label: str) -> str:
    """The value after "- {label}:" in LOCKED VALUES -- the one source for a
    figure that code (not the model) quotes to a customer."""
    prefix = f"- {label}:"
    for line in KISNA_LOCKED_VALUES_TEMPLATE.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    raise LookupError(f"LOCKED VALUES has no line for {label!r}")


# "10 business days" -- quoted by the refund-status route (classifier), taken
# from LOCKED so the code and the model can never disagree on it.
REFUND_PROCESSING_TEXT = _locked_value("Refund processing")


def build_locked_values(*, support_phone: str, support_email: str, support_hours: str) -> str:
    return KISNA_LOCKED_VALUES_TEMPLATE.format(
        support_phone=support_phone,
        support_email=support_email,
        support_hours=support_hours,
    )


# ---------------------------------------------------------------------------
# Campaigns: records with structural expiry. An item is live ON its *_until
# date and gone the day after. prompt_text is what the model may know (None:
# nothing); dropoff_line is the exact line for the drop-off broadcast. The
# making-charge percentages exist ONLY as a drop-off line -- the model never
# sees them. Lines are the client's copy, moved verbatim from the former
# KISNA_DROPOFF_MESSAGE.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CampaignItem:
    id: str
    prompt_text: str | None
    dropoff_line: str | None
    prompt_until: date | None
    dropoff_until: date | None


KISNA_CAMPAIGN_ITEMS: tuple[CampaignItem, ...] = (
    CampaignItem(
        id="making_charges",
        prompt_text=None,
        dropoff_line='• Up to 35% off making charges on diamond jewellery, and up to 20% off on gold jewellery.',
        prompt_until=None,
        dropoff_until=None,
    ),
    CampaignItem(
        id="insurance",
        prompt_text=None,  # permanent benefit -- lives in BRAND PROMISE
        dropoff_line='• Free 1-Year Jewellery Insurance with every purchase.',
        prompt_until=None,
        dropoff_until=None,
    ),
    CampaignItem(
        id="grp",
        prompt_text=(
            "- Gold Rate Protection (GRP) is running now. Never quote its dates; "
            "always direct the customer to the GRP page."
        ),
        dropoff_line="• Gold Rate Protection — lock in today's gold rate before it changes: https://www.kisna.com/pages/gold-rate-protection",
        prompt_until=date(2026, 11, 10),
        dropoff_until=date(2026, 11, 5),
    ),
    CampaignItem(
        id="lucky_draw",
        prompt_text=(
            "- Lucky Draw: prize of 2 scooters and 1 car, 21 August to 30 November "
            "2026, for Indian citizens aged 18 and above, excluding Tamil Nadu. "
            "T&Cs apply. Page: https://www.kisna.com/pages/jewellery-offers"
        ),
        dropoff_line='• Lucky Draw — stand a chance to win 2 scooters and 1 car: https://www.kisna.com/pages/jewellery-offers',
        prompt_until=date(2026, 11, 30),
        dropoff_until=date(2026, 11, 30),
    ),
)

# The order the lines appeared in the client's drop-off message.
_DROPOFF_ORDER: tuple[str, ...] = ('making_charges', 'insurance', 'grp', 'lucky_draw')
_DROPOFF_HEADER = "Just a quick reminder before you go — here's what you don't want to miss at Kisna! ✨\n\n"
_DROPOFF_FOOTER = "\nNeed help? Just reply here and I'll be happy to assist! 😊\n"

# The client's welcome text minus its first "Good Morning!..." line, which is
# now the time-aware kisna_greeting_line() in processors/service_list.py.
KISNA_WELCOME_BODY = """\
Namaste and welcome to Kisna Diamond & Gold. 💎

I'm KIA - your personal jewellery assistant, and I'm delighted to assist you.

Whether you're exploring our latest collections, looking for the perfect jewellery, checking offers, tracking an order, or need any assistance - I'm here to make your Kisna experience simple and delightful. ✨

How may I assist you today? 😊
"""


def _today_ist() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def _live(until: date | None, today: date) -> bool:
    return until is None or today <= until


def build_campaigns_block(today: date | None = None) -> str:
    """Time-bound facts the model may know today (IST). Empty when none."""
    today = today or _today_ist()
    lines = [
        item.prompt_text
        for item in KISNA_CAMPAIGN_ITEMS
        if item.prompt_text and _live(item.prompt_until, today)
    ]
    if not lines:
        return ""
    return "# LIVE CAMPAIGNS (time-bound; never quote dates unless listed here)\n" + "\n".join(lines) + "\n"


def build_dropoff_message(today: date | None = None) -> str:
    """The client's drop-off broadcast with only today's live lines (IST).
    Always a valid message: header + live lines (original order) + footer."""
    today = today or _today_ist()
    by_id = {item.id: item for item in KISNA_CAMPAIGN_ITEMS}
    live = [
        by_id[i].dropoff_line
        for i in _DROPOFF_ORDER
        if by_id[i].dropoff_line and _live(by_id[i].dropoff_until, today)
    ]
    body = "\n".join(live)
    return _DROPOFF_HEADER + (body + "\n" if body else "") + _DROPOFF_FOOTER
