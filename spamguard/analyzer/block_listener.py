import asyncio
import json
import logging
import os
from typing import Awaitable, Callable

import websockets


logger = logging.getLogger(__name__)


BlockHandler = Callable[[int], Awaitable[None]]


class MonadBlockListener:
    def __init__(self, websocket_url: str, on_block: BlockHandler, reconnect_delay: float = 2.0):
        self.websocket_url = websocket_url
        self.on_block = on_block
        self.reconnect_delay = reconnect_delay

    async def listen_forever(self) -> None:
        while True:
            try:
                await self._listen_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("WebSocket listener dropped: %s", exc)
                await asyncio.sleep(self.reconnect_delay)

    async def _listen_once(self) -> None:
        async with websockets.connect(self.websocket_url, ping_interval=20, ping_timeout=20) as ws:
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "eth_subscribe",
                        "params": ["newHeads"],
                    }
                )
            )
            subscription_ack = json.loads(await ws.recv())
            if "error" in subscription_ack:
                raise RuntimeError(f"Subscription failed: {subscription_ack['error']}")

            logger.info("Subscribed to newHeads on %s", self.websocket_url)

            async for raw_message in ws:
                payload = json.loads(raw_message)
                params = payload.get("params", {})
                result = params.get("result")
                if not result:
                    continue

                block_hex = result.get("number")
                if not block_hex:
                    continue

                await self.on_block(int(block_hex, 16))


async def print_block_numbers() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    websocket_url = os.getenv("MONAD_RPC_WSS")
    if not websocket_url:
        raise RuntimeError("MONAD_RPC_WSS must be set to run block_listener.py directly.")

    async def handle(block_number: int) -> None:
        print(f"New block: {block_number}")

    listener = MonadBlockListener(websocket_url, handle)
    await listener.listen_forever()


if __name__ == "__main__":
    asyncio.run(print_block_numbers())
