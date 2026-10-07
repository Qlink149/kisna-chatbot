"""Route counts: each message N times through the classifier exactly as prod
routes a text message: list number stripped, then shortcuts, the regex
overrides, the live LLM, and -- unlike classify_query_for_audit -- prod's
entity extraction plus its category guard (a general / menu_help / greeting
label with a jewellery category becomes product_search, which is how "What if
the ring doesn't fit?" reached the shopping wizard). No chat history unless
--history is given; nothing sent or saved.

    python scripts/route_counts.py --texts texts.json --runs 10 --out counts.json

texts.json is a JSON list of strings. Point PYTHONPATH at another checkout to
measure that code.
"""

import argparse
import asyncio
import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))  # after PYTHONPATH, so another checkout can be measured


async def prod_route(text, history=None):
    """(intent, source) as prod's Classifier.process would conclude."""
    from kisna_chatbot.processors import classifier as C
    from kisna_chatbot.processors.entity_extractor import extract_entities_with_llm

    query = C.strip_list_number(text)
    profile = {"chat_history": list(history or [])}
    r = await C.classify_query_for_audit(query, profile, use_llm=True)
    intent, conf, source = r.get("intent"), r.get("confidence") or 0, r.get("source")
    if source != "llm":
        return intent, source
    entities = dict(r.get("entities") or {})
    if intent in C._ENTITY_EXTRACTION_INTENTS and not C._has_search_entities(entities):
        extracted = await extract_entities_with_llm(user_query=query, client_id="kisna", phone_number="919999999999")
        for k, v in (extracted or {}).items():
            if v is not None and not entities.get(k):
                entities[k] = v
    if entities.get("category") and (
        intent in ("general", "menu_help", "greeting")
        or (intent == "product_info" and conf < C.CLARIFICATION_CONFIDENCE_THRESHOLD)
    ):
        return "product_search", "category_guard"
    return intent, source


async def _one(sem, text, history=None):
    async with sem:
        for attempt in range(3):
            try:
                return await prod_route(text, history)
            except Exception as e:  # noqa: BLE001
                err = f"error:{type(e).__name__}"
                await asyncio.sleep(2 * (attempt + 1))
        return err, "error"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--texts", required=True)
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--out", required=True)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--history", help="JSON list of {role, content} turns before every message")
    args = ap.parse_args()
    texts = json.loads(pathlib.Path(args.texts).read_text(encoding="utf-8"))
    history = json.loads(pathlib.Path(args.history).read_text(encoding="utf-8")) if args.history else None
    sem = asyncio.Semaphore(args.concurrency)
    results = await asyncio.gather(*[_one(sem, t, history) for t in texts for _ in range(args.runs)])
    rows = []
    for i, t in enumerate(texts):
        chunk = results[i * args.runs:(i + 1) * args.runs]
        rows.append({
            "text": t,
            "intents": dict(collections.Counter(c[0] for c in chunk).most_common()),
            "sources": dict(collections.Counter(c[1] for c in chunk).most_common()),
        })
        print(f"{json.dumps(t, ensure_ascii=False):55} {rows[-1]['intents']}  {rows[-1]['sources']}")
    pathlib.Path(args.out).write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
