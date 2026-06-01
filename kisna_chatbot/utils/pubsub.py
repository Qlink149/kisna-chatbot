import asyncio
from collections import defaultdict


class PubSubManager:
    """In-process singleton pub/sub — maps phone_number → list of asyncio.Queue."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        return cls._instance

    def subscribe(self, phone_number: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers[phone_number].append(q)
        return q

    def unsubscribe(self, phone_number: str, queue: asyncio.Queue) -> None:
        subs = self._subscribers.get(phone_number, [])
        if queue in subs:
            subs.remove(queue)

    async def publish(self, phone_number: str, event: dict) -> None:
        for q in list(self._subscribers.get(phone_number, [])):
            await q.put(event)


pubsub = PubSubManager()
