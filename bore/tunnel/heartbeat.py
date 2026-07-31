# borecli/bore/tunnel/heartbeat.py

import asyncio
import json
import logging
import time
from typing import Optional

from bore.frames import make_frame
from bore.protocol import MessageType

logger = logging.getLogger(__name__)


class Heartbeat:
    """
    Maintains the BoreHook tunnel heartbeat.

    Responsibilities
    ----------------
    - Send periodic ping frames
    - Record pong replies
    - Detect dead connections
    - Allow the tunnel client to reconnect
    """

    def __init__(
        self,
        websocket,
        *,
        interval: int = 15,
        timeout: int = 45,
    ):
        self.websocket = websocket

        self.interval = interval
        self.timeout = timeout

        self._running = False
        self._task: Optional[asyncio.Task] = None

        self._last_pong = time.monotonic()

    async def start(self):
        """
        Start the heartbeat loop.
        """

        if self._running:
            return

        logger.info("Heartbeat started")

        self._running = True

        self._task = asyncio.create_task(
            self._run(),
            name="heartbeat",
        )

    async def stop(self):
        """
        Stop the heartbeat loop.
        """

        self._running = False

        if self._task:

            self._task.cancel()

            try:
                await self._task

            except asyncio.CancelledError:
                pass

        logger.info("Heartbeat stopped")

    def pong(self):
        """
        Called by the dispatcher whenever
        a pong frame is received.
        """

        self._last_pong = time.monotonic()

        logger.debug("Heartbeat pong")

    async def _run(self):
        """
        Internal heartbeat loop.
        """

        while self._running:

            try:

                #
                # Send ping
                #

                frame = make_frame(
                    MessageType.PING,
                )

                await self.websocket.send(
                    json.dumps(frame),
                )

                logger.debug("Heartbeat ping")

                #
                # Has the server stopped responding?
                #

                elapsed = (
                    time.monotonic()
                    - self._last_pong
                )

                if elapsed > self.timeout:

                    logger.warning(
                        "Heartbeat timeout "
                        "(%.1fs)",
                        elapsed,
                    )

                    await self.websocket.close()

                    break

                await asyncio.sleep(
                    self.interval,
                )

            except asyncio.CancelledError:
                break

            except Exception as exc:

                logger.exception(
                    "Heartbeat error: %s",
                    exc,
                )

                try:
                    await self.websocket.close()

                except Exception:
                    pass

                break