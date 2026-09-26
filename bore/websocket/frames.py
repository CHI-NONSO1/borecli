from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class FrameType(str, Enum):
    TEXT = "text"
    BINARY = "binary"
    PING = "ping"
    PONG = "pong"
    CLOSE = "close"


class Direction(str, Enum):
    CLIENT_TO_LOCAL = "client_to_local"
    LOCAL_TO_CLIENT = "local_to_client"


@dataclass(slots=True)
class WebSocketFrame:
    """
    Represents a websocket frame flowing through the proxy.

    This class is transport-independent and can be used for
    logging, inspection, replay, and metrics.
    """

    payload: str | bytes

    frame_type: FrameType

    direction: Direction

    connection_id: Optional[str] = None

    timestamp: float = field(
        default_factory=time.time,
    )

    frame_id: str = field(
        default_factory=lambda: str(uuid.uuid4()),
    )

    @property
    def is_text(self) -> bool:
        return self.frame_type == FrameType.TEXT

    @property
    def is_binary(self) -> bool:
        return self.frame_type == FrameType.BINARY

    @property
    def size(self) -> int:
        if isinstance(self.payload, bytes):
            return len(self.payload)

        return len(
            self.payload.encode("utf-8")
        )

    def as_json(self) -> Optional[Any]:
        """
        Return parsed JSON if the payload contains valid JSON.
        """

        if not self.is_text:
            return None

        try:
            return json.loads(self.payload)

        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            return None

    def serialize(self) -> dict:
        """
        Convert to a JSON-safe dictionary.
        """

        if self.is_binary:
            payload = base64.b64encode(
                self.payload
            ).decode("ascii")

            encoding = "base64"

        else:
            payload = self.payload
            encoding = "utf-8"

        return {
            "frame_id": self.frame_id,
            "connection_id": self.connection_id,
            "timestamp": self.timestamp,
            "direction": self.direction.value,
            "type": self.frame_type.value,
            "size": self.size,
            "encoding": encoding,
            "payload": payload,
        }

    @classmethod
    def text(
        cls,
        payload: str,
        direction: Direction,
        connection_id: str | None = None,
    ):
        return cls(
            payload=payload,
            frame_type=FrameType.TEXT,
            direction=direction,
            connection_id=connection_id,
        )

    @classmethod
    def binary(
        cls,
        payload: bytes,
        direction: Direction,
        connection_id: str | None = None,
    ):
        return cls(
            payload=payload,
            frame_type=FrameType.BINARY,
            direction=direction,
            connection_id=connection_id,
        )

    @classmethod
    def ping(
        cls,
        payload: bytes = b"",
        connection_id: str | None = None,
    ):
        return cls(
            payload=payload,
            frame_type=FrameType.PING,
            direction=Direction.CLIENT_TO_LOCAL,
            connection_id=connection_id,
        )

    @classmethod
    def pong(
        cls,
        payload: bytes = b"",
        connection_id: str | None = None,
    ):
        return cls(
            payload=payload,
            frame_type=FrameType.PONG,
            direction=Direction.LOCAL_TO_CLIENT,
            connection_id=connection_id,
        )

    @classmethod
    def close(
        cls,
        payload: str = "",
        connection_id: str | None = None,
    ):
        return cls(
            payload=payload,
            frame_type=FrameType.CLOSE,
            direction=Direction.CLIENT_TO_LOCAL,
            connection_id=connection_id,
        )