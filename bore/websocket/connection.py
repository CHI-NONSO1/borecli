from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from websockets.client import WebSocketClientProtocol


class ConnectionState(str, Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass(slots=True)
class ConnectionStats:
    bytes_sent: int = 0
    bytes_received: int = 0

    messages_sent: int = 0
    messages_received: int = 0

    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    def sent(self, message):
        size = len(message) if isinstance(message, bytes) else len(str(message))

        self.bytes_sent += size
        self.messages_sent += 1
        self.last_activity = time.time()

    def received(self, message):
        size = len(message) if isinstance(message, bytes) else len(str(message))

        self.bytes_received += size
        self.messages_received += 1
        self.last_activity = time.time()

    @property
    def uptime(self):
        return time.time() - self.created_at

    @property
    def idle(self):
        return time.time() - self.last_activity


@dataclass(slots=True)
class WebSocketConnection:
    """
    Represents one localhost websocket connection.

    This class stores metadata only.
    """

    websocket: WebSocketClientProtocol
    url: str

    connection_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    tunnel_id: Optional[str] = None

    state: ConnectionState = ConnectionState.CONNECTING

    stats: ConnectionStats = field(default_factory=ConnectionStats)

    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    metadata: dict = field(default_factory=dict)

    @property
    def connected(self) -> bool:
        return self.state == ConnectionState.CONNECTED

    def mark_connected(self):
        self.state = ConnectionState.CONNECTED

    def mark_closing(self):
        self.state = ConnectionState.CLOSING

    def mark_closed(self):
        self.state = ConnectionState.CLOSED

    def record_sent(self, message):
        self.stats.sent(message)

    def record_received(self, message):
        self.stats.received(message)

    def to_dict(self):
        return {
            "connection_id": self.connection_id,
            "tunnel_id": self.tunnel_id,
            "url": self.url,
            "state": self.state.value,
            "uptime": self.stats.uptime,
            "idle": self.stats.idle,
            "messages_sent": self.stats.messages_sent,
            "messages_received": self.stats.messages_received,
            "bytes_sent": self.stats.bytes_sent,
            "bytes_received": self.stats.bytes_received,
        }