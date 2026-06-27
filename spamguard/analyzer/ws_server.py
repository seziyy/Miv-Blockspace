import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Set

import websockets
from websockets.exceptions import ConnectionClosed


logger = logging.getLogger(__name__)

HOST = "0.0.0.0"
PORT = 8765
MAX_HISTORY = 30
HISTORY_PATH = Path(__file__).resolve().parent / "ws_history.json"
CLIENTS: Set[Any] = set()
HISTORY: List[Dict[str, Any]] = []


def _cors_headers(origin: str | None) -> List[tuple[str, str]]:
    return [
        ("Access-Control-Allow-Origin", origin or "*"),
        ("Access-Control-Allow-Credentials", "true"),
    ]


def _load_history() -> List[Dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []

    try:
        payload = json.loads(HISTORY_PATH.read_text())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load WebSocket history: %s", exc)
        return []

    if not isinstance(payload, list):
        return []
    return payload[-MAX_HISTORY:]


def _save_history() -> None:
    try:
        HISTORY_PATH.write_text(json.dumps(HISTORY[-MAX_HISTORY:]))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to persist WebSocket history: %s", exc)


async def _client_handler(websocket: Any) -> None:
    client_ip = getattr(websocket, "remote_address", None)
    client_host = client_ip[0] if isinstance(client_ip, tuple) and client_ip else "unknown"
    CLIENTS.add(websocket)
    logger.info("Frontend client connected: %s", client_host)

    try:
        await websocket.send(json.dumps({"type": "history", "blocks": HISTORY}))

        async for _message in websocket:
            # Frontend is read-only for now; ignore inbound messages.
            continue
    except ConnectionClosed:
        pass
    finally:
        CLIENTS.discard(websocket)
        logger.info("Frontend client disconnected: %s", client_host)


async def broadcast(data: Dict[str, Any]) -> None:
    HISTORY.append(data)
    if len(HISTORY) > MAX_HISTORY:
        del HISTORY[0 : len(HISTORY) - MAX_HISTORY]
    _save_history()

    if not CLIENTS:
        return

    message = json.dumps({"type": "block", "data": data})
    disconnected: List[Any] = []
    for client in list(CLIENTS):
        try:
            await client.send(message)
        except ConnectionClosed:
            disconnected.append(client)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Broadcast to frontend client failed: %s", exc)
            disconnected.append(client)

    for client in disconnected:
        CLIENTS.discard(client)


async def start_server() -> Any:
    HISTORY.clear()
    HISTORY.extend(_load_history())

    def process_response(_connection: Any, request: Any, response: Any) -> Any:
        origin = None
        headers = getattr(request, "headers", None)
        if headers is not None:
            origin = headers.get("Origin")
        for key, value in _cors_headers(origin):
            response.headers[key] = value
        return response

    server = await websockets.serve(
        _client_handler,
        HOST,
        PORT,
        process_response=process_response,
    )
    logger.info("WebSocket broadcast server listening on ws://%s:%s", HOST, PORT)
    return server
