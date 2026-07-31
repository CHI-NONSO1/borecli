import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

import websockets
from websockets.client import WebSocketClientProtocol
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)


@dataclass
class ManagedConnection:
    connection_id: str
    websocket: WebSocketClientProtocol
    url: str

    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    bytes_sent: int = 0
    bytes_received: int = 0

    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def connected(self) -> bool:
        return not self.websocket.closed


class WebSocketManager:
    """
    Manages websocket connections from the CLI to localhost.

    This class DOES NOT proxy websocket traffic.
    It only manages the lifecycle of localhost websocket connections.
    """

    def __init__(self):
        self._connections: Dict[str, ManagedConnection] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        connection_id: str,
        local_port: int,
        path: str,
        query: str = "",
        headers: Optional[dict] = None,
    ) -> ManagedConnection:

        url = f"ws://127.0.0.1:{local_port}{path}"

        if query:
            url += f"?{query}"

        logger.info("Connecting to %s", url)

        ws = await websockets.connect(
            url,
            additional_headers=headers or {},
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_size=None,
            max_queue=1024,
        )

        connection = ManagedConnection(
            connection_id=connection_id,
            websocket=ws,
            url=url,
        )

        async with self._lock:
            self._connections[connection_id] = connection

        logger.info("Connected websocket %s", connection_id)

        return connection

    async def send(
        self,
        connection_id: str,
        message,
    ):

        conn = self.get(connection_id)

        if conn is None:
            raise KeyError(connection_id)

        async with conn.send_lock:

            await conn.websocket.send(message)

            size = len(message) if isinstance(message, bytes) else len(str(message))

            conn.bytes_sent += size
            conn.last_activity = time.time()

    async def recv(
        self,
        connection_id: str,
    ):

        conn = self.get(connection_id)

        if conn is None:
            raise KeyError(connection_id)

        try:

            message = await conn.websocket.recv()

            size = len(message) if isinstance(message, bytes) else len(str(message))

            conn.bytes_received += size
            conn.last_activity = time.time()

            return message

        except ConnectionClosed:
            await self.close(connection_id)
            raise

    async def close(self, connection_id: str):

        async with self._lock:
            conn = self._connections.pop(connection_id, None)

        if conn is None:
            return

        try:
            await conn.websocket.close()
        except Exception:
            logger.exception("Failed closing websocket %s", connection_id)

    async def close_all(self):

        ids = list(self._connections.keys())

        await asyncio.gather(
            *(self.close(cid) for cid in ids),
            return_exceptions=True,
        )

    def get(self, connection_id: str) -> Optional[ManagedConnection]:
        return self._connections.get(connection_id)

    def exists(self, connection_id: str) -> bool:
        return connection_id in self._connections

    def count(self) -> int:
        return len(self._connections)

    def stats(self):

        now = time.time()

        return {
            cid: {
                "url": conn.url,
                "connected": conn.connected,
                "uptime": now - conn.created_at,
                "idle": now - conn.last_activity,
                "bytes_sent": conn.bytes_sent,
                "bytes_received": conn.bytes_received,
            }
            for cid, conn in self._connections.items()
        }