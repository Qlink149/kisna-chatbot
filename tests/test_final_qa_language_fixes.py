"""Three pre-existing language defects the final QA sweep measured.

None of these is a regression -- all three predate the recent work. All three
are the same failure the handover names in §0: a rule written for the
languages someone had in front of them, silently wrong for the rest.

5.1  Assamese was answered in Bengali on every prose turn (14/14). The Bengali
     script block accepted "as" but defaulted to "bn" whenever the classifier
     did not volunteer the label, which was every turn. Assamese and Bengali
     share a block but not an alphabet -- ৰ (U+09F0) and ৱ (U+09F1) are not
     used in Bengali orthography -- so the letters themselves settle it.

5.2  A carat weight written in native script became a rupee budget: "10 कैरेट
     से कम की अंगूठी है क्या?" returned max_price=10000 and the same sentence
     ending "दिखाओ" returned 100000 -- two different invented numbers, which
     is what tells you it is the model guessing rather than a regex. English
     ("under 10 carats") was already guarded; the guard was Latin-only.

5.3  Punjabi ਮੁੰਦਰੀਆਂ (rings) returned EARRINGS on a full sentence (3/3) and
     rings when the sentence was short (0/3) -- the identical shape already
     recorded for Gujarati વીંટી, in a language nobody had checked.
"""

import os
import unittest

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.main import app  # noqa: F401,E402
from kisna_chatbot.processors.classifier import resolve_reply_language  # noqa: E402
from kisna_chatbot.processors.entity_extractor import (  # noqa: E402
    finalize_search_entities,
)


class AssameseIsNotBengaliTests(unittest.TestCase):
    ASSAMESE = (
        "মোক ২০ হাজাৰতকৈ কম দামৰ সোণৰ আঙঠি দেখুৱাওক",
        "আপোনালোকৰ দোকান গুৱাহাটীত আছেনে?",
        "মই এটা হীৰাৰ আঙঠি বিচাৰিছো",
        "আজিৰ সোণৰ দাম কিমান?",
    )
    BENGALI = (
        "আমাকে ২০ হাজার টাকার কমে সোনার আংটি দেখান",
        "আপনাদের দোকান কলকাতায় আছে কি?",
        "আমি একটি হীরার আংটি খুঁজছি",
        "আজকের সোনার দাম কত?",
        "হ্যাঁ",
    )

    def test_assamese_letters_settle_the_language(self):
        for text in self.ASSAMESE:
            # Even with no label at all, and even against a wrong one.
            self.assertEqual(resolve_reply_language(None, text), "as", text)
            self.assertEqual(resolve_reply_language("bn", text), "as", text)

    def test_bengali_is_never_dragged_into_assamese(self):
        for text in self.BENGALI:
            self.assertEqual(resolve_reply_language(None, text), "bn", text)
            self.assertEqual(resolve_reply_language("hi", text), "bn", text)

    def test_an_explicit_assamese_label_still_wins_without_the_letters(self):
        # Short turns carry no ৰ/ৱ. The label decides, as it always did.
        self.assertEqual(resolve_reply_language("as", "হয়"), "as")


def _finalized(query: str, **entities):
    return finalize_search_entities(dict(entities), query=query)


class CaratIsNotAPriceTests(unittest.TestCase):
    def test_native_script_carat_drops_an_invented_price(self):
        for query, invented in (
            ("10 कैरेट से कम की अंगूठी है क्या?", 10000),
            ("10 कैरेट से कम की अंगूठी दिखाओ", 100000),
            ("10 காரட்டுக்கு கீழ் மோதிரம் காட்டுங்கள்", 10000),
            ("10 કેરેટથી ઓછી વીંટી બતાવો", 10000),
        ):
            out = _finalized(query, category="ring", max_price=invented)
            self.assertIsNone(out.get("max_price"), query)

    def test_a_real_budget_beside_a_carat_weight_survives(self):
        # The guard drops an INVENTED price, not a stated one.
        out = _finalized(
            "10 कैरेट की अंगूठी 50 हज़ार के अंदर", category="ring", max_price=50000
        )
        self.assertEqual(out.get("max_price"), 50000)
        out = _finalized(
            "10 கேரட் மோதிரம் ₹50000 க்குள்", category="ring", max_price=50000
        )
        self.assertEqual(out.get("max_price"), 50000)

    def test_a_budget_in_plain_digits_beside_a_carat_weight_survives(self):
        # No cue word at all -- just a four-figure number, which is money.
        # Nobody asks for a 50,000-carat ring.
        for query in (
            "10 कैरेट की अंगूठी 50000 से कम",
            "10 காரட் மோதிரம் 75000 வரை",
        ):
            out = _finalized(query, category="ring", max_price=50000)
            self.assertEqual(out.get("max_price"), 50000, query)

    def test_ordinary_budgets_are_untouched(self):
        for query, price in (
            ("20 हज़ार से कम की सोने की अंगूठी दिखाओ", 20000),
            ("मेरा बजट 250000 है", 250000),
            ("show me gold rings under 20000", 20000),
        ):
            out = _finalized(query, category="ring", max_price=price)
            self.assertEqual(out.get("max_price"), price, query)


class NativeRingWordsTests(unittest.TestCase):
    def test_a_native_ring_word_overrides_an_earring_reading(self):
        for query in (
            "ਔਰਤਾਂ ਲਈ 200000 ਤੋਂ ਘੱਟ ਦੀਆਂ ਹੀਰੇ ਦੀਆਂ ਮੁੰਦਰੀਆਂ ਦਿਖਾਓ, ਤੁਰੰਤ ਡਿਲਿਵਰੀ",
            "ਮੈਨੂੰ ਹੀਰੇ ਦੀ ਮੁੰਦਰੀ ਦਿਖਾਓ",
            "મહિલાઓ માટે 200000 થી ઓછી હીરાની વીંટી બતાવો",
        ):
            out = _finalized(query, category="earring")
            self.assertEqual(out.get("category"), "ring", query)

    def test_the_categories_list_is_corrected_with_it(self):
        out = _finalized(
            "ਮੈਨੂੰ ਮੁੰਦਰੀਆਂ ਦਿਖਾਓ",
            category="earring",
            categories=["earring", "pendant"],
        )
        self.assertEqual(out.get("category"), "ring")
        self.assertEqual(out.get("categories"), ["ring", "pendant"])

    def test_a_real_earring_request_stays_an_earring(self):
        for query in (
            "ਔਰਤਾਂ ਲਈ 200000 ਤੋਂ ਘੱਟ ਦੀਆਂ ਹੀਰੇ ਦੀਆਂ ਵਾਲੀਆਂ ਦਿਖਾਓ",
            "મને કાનની બુટ્ટી બતાવો",
            "show me diamond earrings",
        ):
            out = _finalized(query, category="earring")
            self.assertEqual(out.get("category"), "earring", query)


if __name__ == "__main__":
    unittest.main()
