"""Which script is this text written in?

Deliberately a leaf module: no project imports, so it can be used from the
entity extractor, the classifier and the reply composer without reviving the
circular-import trap those three already work around.

WHY THIS EXISTS. Seven places asked "can the Latin regex read this, or must I
trust the LLM?" and each answered it with a hardcoded Devanagari-to-Malayalam
range (U+0900-U+0D7F). That was correct while every supported language was
either Latin or Indic. Adding Urdu -- Arabic script -- made all seven wrong at
once, and the failures were severe rather than cosmetic: an Urdu product search
was classified as SPAM and rerouted to the general agent, the evidence gate
deleted the metal and the audience the model had read correctly, and every
composed Urdu reply was rejected as an "echo" and fell back to English.

So the question is answered by what a character IS, not by which block it sits
in. A list of ranges has to be extended for every language ever added, and
whoever adds the next one will not know to look here.
"""


def is_latin_letter(ch: str) -> bool:
    """True for A-Z / a-z only."""
    return ("A" <= ch <= "Z") or ("a" <= ch <= "z")


def has_non_latin_letters(text: str | None) -> bool:
    """True when the text contains a letter outside the ASCII Latin alphabet.

    Devanagari, Gujarati, Gurmukhi, Bengali, Odia, Tamil, Telugu, Kannada,
    Malayalam, Arabic/Urdu -- and anything else with a real alphabet. Digits,
    punctuation, emoji and pure ASCII are all False, so "50000", "😍" and
    "show me rings" are unaffected.
    """
    if not text:
        return False
    return any(ch.isalpha() and not is_latin_letter(ch) for ch in text)


def has_latin_letters(text: str | None) -> bool:
    """True when the text contains at least one A-Z / a-z character."""
    if not text:
        return False
    return any(is_latin_letter(ch) for ch in text)


def has_letters(text: str | None) -> bool:
    """True when the text contains a letter in ANY script.

    Used to tell real language from keyboard mash: a message written in a
    script we have never heard of is still somebody trying to talk to us, and
    treating it as spam is worse than trying to answer it.
    """
    if not text:
        return False
    return any(ch.isalpha() for ch in text)
