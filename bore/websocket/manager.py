from __future__ import annotations

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
    close_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    closing: bool = False
    closed: bool = False

    @property
    def connected(self) -> bool:
        """
        Return whether the WebSocket is currently usable.

        The explicit lifecycle flags are checked first so that the
        manager does not attempt to reuse a connection while another
        task is shutting it down.
        """

        if self.closing or self.closed:
            return False

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
            existing = self._connections.get(connection_id)

            if existing is not None and existing.connected:
                # Do not leave an orphaned WebSocket behind when a caller
                # accidentally attempts to reuse an active connection ID.
                await ws.close()
                raise RuntimeError(
                    f"WebSocket connection already exists: {connection_id}"
                )

            self._connections[connection_id] = connection

        logger.info(
            "Connected websocket %s",
            connection_id,
        )

        return connection

    async def send(
        self,
        connection_id: str,
        message,
    ):
        conn = self.get(connection_id)

        if conn is None:
            raise KeyError(connection_id)

        if not conn.connected:
            raise ConnectionError(
                f"WebSocket connection is closed: {connection_id}"
            )

        async with conn.send_lock:
            if not conn.connected:
                raise ConnectionError(
                    f"WebSocket connection is closed: {connection_id}"
                )

            try:
                await conn.websocket.send(message)

            except asyncio.CancelledError:
                raise

            except ConnectionClosed:
                await self._remove_if_current(
                    connection_id,
                    conn,
                )
                raise

            except Exception:
                await self._remove_if_current(
                    connection_id,
                    conn,
                )
                raise

            size = (
                len(message)
                if isinstance(message, bytes)
                else len(str(message))
            )

            conn.bytes_sent += size
            conn.last_activity = time.time()

    async def recv(
        self,
        connection_id: str,
    ):
        conn = self.get(connection_id)

        if conn is None:
            raise KeyError(connection_id)

        if not conn.connected:
            raise ConnectionError(
                f"WebSocket connection is closed: {connection_id}"
            )

        try:
            message = await conn.websocket.recv()

        except asyncio.CancelledError:
            raise

        except ConnectionClosed:
            await self._remove_if_current(
                connection_id,
                conn,
            )
            raise

        except Exception:
            await self._remove_if_current(
                connection_id,
                conn,
            )
            raise

        size = (
            len(message)
            if isinstance(message, bytes)
            else len(str(message))
        )

        conn.bytes_received += size
        conn.last_activity = time.time()

        return message

    async def close(
        self,
        connection_id: str,
    ):
        async with self._lock:
            conn = self._connections.get(connection_id)

        if conn is None:
            return

        await self._close_connection(
            connection_id,
            conn,
        )

    async def _close_connection(
        self,
        connection_id: str,
        conn: ManagedConnection,
    ):
        """
        Close one connection exactly once.

        Multiple tasks can reach this method at the same time during
        shutdown. close_lock makes the operation idempotent.
        """

        async with conn.close_lock:
            if conn.closed:
                await self._remove_if_current(
                    connection_id,
                    conn,
                )
                return

            conn.closing = True

            try:
                await conn.websocket.close()

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                # Closing an already-closed socket is a normal shutdown
                # race. Keep the detail in logs without producing a
                # traceback for the user.
                logger.debug(
                    "WebSocket close completed with an expected shutdown error "
                    "for %s: %s",
                    connection_id,
                    exc,
                )

            finally:
                conn.closed = True
                conn.closing = False

                await self._remove_if_current(
                    connection_id,
                    conn,
                )

    async def _remove_if_current(
        self,
        connection_id: str,
        connection: ManagedConnection,
    ):
        """
        Remove a connection only if the manager still points to the same
        connection object.

        This prevents an old connection from accidentally removing a
        newer connection that reused the same connection ID.
        """

        async with self._lock:
            current = self._connections.get(connection_id)

            if current is connection:
                self._connections.pop(
                    connection_id,
                    None,
                )

    async def close_all(self):
        """
        Close every currently managed connection.

        A stable snapshot is taken under the manager lock so that
        concurrent recv/send cleanup cannot mutate the dictionary while
        it is being iterated.
        """

        async with self._lock:
            connections = list(
                self._connections.items()
            )

        await asyncio.gather(
            *(
                self._close_connection(
                    connection_id,
                    connection,
                )
                for connection_id, connection in connections
            ),
            return_exceptions=True,
        )

    def get(
        self,
        connection_id: str,
    ) -> Optional[ManagedConnection]:
        return self._connections.get(connection_id)

    def exists(
        self,
        connection_id: str,
    ) -> bool:
        return connection_id in self._connections

    def count(self) -> int:
        return len(self._connections)

    def stats(self):
        now = time.time()

        return {
            connection_id: {
                "url": connection.url,
                "connected": connection.connected,
                "uptime": now - connection.created_at,
                "idle": now - connection.last_activity,
                "bytes_sent": connection.bytes_sent,
                "bytes_received": connection.bytes_received,
            }
            for connection_id, connection in self._connections.items()
        }