from enum import Enum


class ListIds(Enum):
    """All list ids."""

    SERVICE_LIST_ID = "service_list"


class QuickReplyId(Enum):
    """All quick reply ids."""

    EVENT_TYPE = "event_type"
    RATING_REQUEST = "rating_request"
    COMPLAINT_REGISTER = "complaint_register"
    CLARIFY_BROWSE = "clarify$browse"
    CLARIFY_ASK = "clarify$ask"
    CLARIFY_STORE_YES = "clarify$store_yes"
    CLARIFY_STORE_NO = "clarify$store_no"
    CLARIFY_TRACK = "clarify$track"
    CLARIFY_COMPLAINT = "clarify$complaint"
    CLARIFY_OFFERS = "clarify$offers"
    CLARIFY_VIEW_OFFERS = "clarify$view_offers"
    CLARIFY_FIND_STORE = "clarify$find_store"
    CLARIFY_ASK_QUESTION = "clarify$ask_question"
    NON_TEXT_BROWSE = "non_text$browse"


class FlowId(Enum):
    """Kisna / shared WhatsApp flow ids (Gupshup)."""

    PRE_ORDER_FLOW = "1234567890"
    COMPLAINT_FLOW = "1499346684904288"
    STORE_VISIT_FLOW = "1234567892"


class FLowId(Enum):
    """All flow ids."""

    BOOK_SPOT_FLOW_ID = "1244838263732533"
    INTELLIGENT_EVENT_REGISTRATION_FLOW_ID = "1262293402565331"
    MAIN_EVENT_REGISTRATION_FLOW_ID = "1364918277991593"
    SPEAKER_REGISTRATION = "4119093268366665"

    SITE_VISIT = "1549895279663943"
    GIT_SITE_VISIT = "685081584337677"

    DAMAGE_COMPLAINT = "1499346684904288"

    STORE_LOCATOR = "1657336852268812"
    STORE_VISIT_DATETIME = "1519939742807085"
