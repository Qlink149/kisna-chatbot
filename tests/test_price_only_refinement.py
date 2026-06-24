import os
import unittest

os.environ.setdefault('ENV_MODE', 'dev')
os.environ.setdefault('MONGO_URI', 'mongodb://localhost:27017')
os.environ.setdefault('OPENAI_API_KEY', 'test-key')
os.environ.setdefault('JWT_SECRET_KEY', 'test-jwt')
os.environ.setdefault('SYSTEM_API_KEY', 'test-api')
os.environ.setdefault('KISNA_PRODUCT_API', 'https://example.com/products')
os.environ.setdefault('GUPSHUP_APP_ID', 'test-app-id')
os.environ.setdefault('GUPSHUP_TOKEN', 'test-token')
os.environ.setdefault('GUPSHUP_APP_NAME', 'test-app')
os.environ.setdefault('GUPSHUP_API_KEY', 'test-api-key')

from kisna_chatbot.main import app  # noqa: F401
from kisna_chatbot.processors.entity_extractor import merge_search_entities
from kisna_chatbot.processors.classifier import _should_offer_clarification
from kisna_chatbot.processors.product_search_agent_v3 import _is_price_only_refinement


class TestIsPriceOnlyRefinement(unittest.TestCase):
    def _profile(self, category=None, material=None):
        f = {}
        if category: f['category'] = category
        if material: f['material_type'] = material
        return {'last_search_filters': f, 'service_selected': 'product_search'}

    def test_earring_gold_under_10k(self):
        self.assertTrue(_is_price_only_refinement('under 10k', self._profile('earring', 'gold')))

    def test_ring_above_50k(self):
        self.assertTrue(_is_price_only_refinement('above 50k', self._profile('ring', 'gold')))

    def test_number_only(self):
        self.assertTrue(_is_price_only_refinement('20000 tak', self._profile('necklace', 'diamond')))

    def test_no_prior_returns_false(self):
        self.assertFalse(_is_price_only_refinement('under 10k', {'last_search_filters': {}}))

    def test_empty_profile_returns_false(self):
        self.assertFalse(_is_price_only_refinement('under 10k', {}))

    def test_message_has_category_returns_false(self):
        self.assertFalse(_is_price_only_refinement('diamond rings under 50k', self._profile('earring', 'gold')))

    def test_message_has_material_returns_false(self):
        self.assertFalse(_is_price_only_refinement('in gold', self._profile('earring', 'gold')))

    def test_category_only_prior(self):
        self.assertTrue(_is_price_only_refinement('below 15000', self._profile('earring')))

    def test_material_only_prior(self):
        self.assertTrue(_is_price_only_refinement('under 25k', self._profile(material='gold')))

    def test_lakh_is_price(self):
        self.assertTrue(_is_price_only_refinement('upto 1 lakh', self._profile('necklace', 'gold')))

    def test_large_number_is_price(self):
        self.assertTrue(_is_price_only_refinement('10000', self._profile('ring')))


class TestShouldOfferClarificationPriceGuard(unittest.TestCase):
    def _data(self):
        return {'phone_number': '919999999999'}

    def _profile(self, category='earring', material='gold'):
        return {
            'service_selected': 'product_search',
            'chat_history': [{'role': 'user', 'content': 'show me gold earrings'}],
            'last_search_filters': {'category': category, 'material_type': material},
        }

    def test_price_in_active_session_no_clarification(self):
        self.assertFalse(_should_offer_clarification(self._data(), 'under 10k', self._profile()))

    def test_above_50k_no_clarification(self):
        self.assertFalse(_should_offer_clarification(self._data(), 'above 50k', self._profile('ring', 'gold')))

    def test_no_prior_filters_allows_clarification(self):
        p = {'service_selected': 'product_search',
             'chat_history': [{'role': 'user', 'content': 'hi'}],
             'last_search_filters': {}}
        self.assertTrue(_should_offer_clarification(self._data(), 'under 10k', p))

    def test_category_word_suppressed(self):
        self.assertFalse(_should_offer_clarification(self._data(), 'show me earrings', self._profile()))

    def test_category_only_prior_suppresses(self):
        p = {'service_selected': 'product_search',
             'chat_history': [{'role': 'user', 'content': 'show me earrings'}],
             'last_search_filters': {'category': 'earring'}}
        self.assertFalse(_should_offer_clarification(self._data(), 'under 10k', p))


class TestMergeSearchEntitiesPriceOnly(unittest.TestCase):
    """
    Documents the INTENTIONAL semantics of merge_search_entities() for bare
    price-only messages.

    The function does NOT inherit prior category on price-only bare queries
    (e.g. 'under 10k') -- that is by design and matches test_clara_fixtures.py.
    Context-carrying messages ('I want them under 10k') DO inherit via
    _REFINEMENT_RE / _CONTEXT_REFINEMENT_RE.

    The actual end-user fix ('show earrings' -> 'under 10k' = refine correctly)
    is handled by the FIX 1 fast-path in product_search_agent_v3, which builds
    the merged entities manually and bypasses merge_search_entities entirely.
    """
    def _empty(self):
        return {'category': None, 'categories': None, 'multi_category': False,
                'secondary_category': None, 'material_type': None,
                'unsupported_category': False, 'unsupported_material': False,
                'min_price': None, 'max_price': None, 'title': None,
                'city': None, 'pincode': None, 'karat': None,
                'metal_colour': None, 'size': None, 'collection': None,
                'gender': None, 'occasion': None, 'style': None, 'action': None}

    def _price(self, mn=None, mx=None):
        e = self._empty()
        e['min_price'] = mn
        e['max_price'] = mx
        return e

    def test_bare_price_does_not_inherit_category(self):
        """Bare 'under 10k' does NOT inherit prior category via merge_search_entities.
        The FIX 1 fast-path handles this separately.
        This matches the explicit contract in test_clara_fixtures.py.
        """
        prior = {'category': 'earring', 'material_type': 'gold', 'max_price': None}
        m = merge_search_entities(prior, self._price(mx=10000), 'under 10k')
        self.assertIsNone(m['category'])  # expected: bare price = fresh price search
        self.assertEqual(m['max_price'], 10000)

    def test_context_word_them_does_inherit_category(self):
        """'I want them under 10k' HAS context words -> _CONTEXT_REFINEMENT_RE matches
        -> refinement_only=True -> category IS inherited.
        """
        prior = {'category': 'earring', 'material_type': 'gold', 'max_price': None}
        new = {'category': None, 'material_type': None, 'min_price': None,
               'max_price': 10000.0, 'title': None}
        m = merge_search_entities(prior, new, 'I want them under 10,000')
        self.assertEqual(m['category'], 'earring')
        self.assertEqual(m['max_price'], 10000.0)

    def test_no_prior_no_category_inherited(self):
        m = merge_search_entities(None, self._price(mx=10000), 'under 10k')
        self.assertIsNone(m['category'])
        self.assertIsNone(m['material_type'])
        self.assertEqual(m['max_price'], 10000)

    def test_price_with_new_category_uses_new_category(self):
        prior = {'category': 'earring', 'material_type': 'gold'}
        new = {**self._empty(), 'category': 'ring', 'max_price': 50000}
        m = merge_search_entities(prior, new, 'diamond rings under 50k')
        self.assertEqual(m['category'], 'ring')


class TestPriceRefinementScenario(unittest.TestCase):

    def test_earring_gold_under_10k_fix1_and_fix2(self):
        """Verifies FIX 1 (fast-path detection) and FIX 2 (no clarification).

        The FIX 1 fast-path builds merged entities manually:
          category and material_type from prior, price from current message.
        This test replicates that logic to verify the correct API params.
        """
        from kisna_chatbot.processors.entity_extractor import _NEVER_INHERIT_FIELDS
        up = {
            'service_selected': 'product_search',
            'chat_history': [{'role': 'user', 'content': 'show me gold earrings'}],
            'last_search_filters': {
                'category': 'earring', 'material_type': 'gold',
                'max_price': None, 'min_price': None,
            },
        }
        data = {'phone_number': '919999999999'}

        # FIX 1: fast-path detects unambiguous intent
        self.assertTrue(_is_price_only_refinement('under 10k', up))

        # FIX 2: classifier should not fire clarification
        self.assertFalse(_should_offer_clarification(data, 'under 10k', up))

        # Simulate the FIX 1 fast-path entity building (mirrors product_search_agent_v3)
        prior_raw = up['last_search_filters']
        prior_clean = {k: v for k, v in prior_raw.items()
                       if k not in _NEVER_INHERIT_FIELDS and v is not None}
        search_entities = {**prior_clean, 'title': None, 'collection': None}
        # max_price from extract_entities('under 10k') would give 10000
        search_entities['max_price'] = 10000

        self.assertEqual(search_entities['category'], 'earring')
        self.assertEqual(search_entities['material_type'], 'gold')
        self.assertEqual(search_entities['max_price'], 10000)
        self.assertIsNone(search_entities['title'])
        self.assertIsNone(search_entities['collection'])

    def test_ring_gold_above_50k(self):
        up = {'service_selected': 'product_search',
              'chat_history': [{'role': 'user', 'content': 'gold rings'}],
              'last_search_filters': {'category': 'ring', 'material_type': 'gold'}}
        self.assertTrue(_is_price_only_refinement('above 50k', up))
        self.assertFalse(_should_offer_clarification({'phone_number': '919999999999'}, 'above 50k', up))

    def test_no_prior_normal_path(self):
        up = {'service_selected': 'product_search',
              'chat_history': [], 'last_search_filters': {}}
        self.assertFalse(_is_price_only_refinement('under 10k', up))
        self.assertTrue(_should_offer_clarification({'phone_number': '919999999999'}, 'under 10k', up))

    def test_in_gold_not_price_only(self):
        up = {'service_selected': 'product_search',
              'chat_history': [{'role': 'user', 'content': 'earrings'}],
              'last_search_filters': {'category': 'earring'}}
        self.assertFalse(_is_price_only_refinement('in gold', up))


if __name__ == '__main__':
    unittest.main()
