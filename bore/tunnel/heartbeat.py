import asyncio
import contextlib
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

    The heartbeat is deliberately defensive around WebSocket shutdown.
    The main tunnel connection may close the WebSocket at the same time
    that this task is sending a ping or detecting a timeout.
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

        self._running = True
        self._last_pong = time.monotonic()

        logger.info("Heartbeat started")

        self._task = asyncio.create_task(
            self._run(),
            name="heartbeat",
        )

    async def stop(self):
        """
        Stop the heartbeat loop.

        Cancellation is intentionally handled here so that shutdown of
        the tunnel does not produce noisy asyncio cancellation errors.
        """

        if not self._running and self._task is None:
            return

        self._running = False

        task = self._task
        self._task = None

        if task is not None:
            current_task = asyncio.current_task()

            # Never await/cancel ourselves.
            if task is not current_task:
                task.cancel()

                with contextlib.suppress(
                    asyncio.CancelledError,
                    Exception,
                ):
                    await task

        logger.info("Heartbeat stopped")

    def pong(self):
        """
        Called by the dispatcher whenever
        a pong frame is received.
        """

        self._last_pong = time.monotonic()

        logger.debug("Heartbeat pong")

    async def _close_websocket(self):
        """
        Close the WebSocket safely.

        The main tunnel task may already have closed the connection.
        WebSocket shutdown is therefore treated as best-effort and
        shutdown-related exceptions are intentionally suppressed.
        """

        try:
            await self.websocket.close()

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            logger.debug(
                "WebSocket already closed or unavailable during heartbeat shutdown: %s",
                exc,
            )

    async def _run(self):
        """
        Internal heartbeat loop.

        Any WebSocket failure causes the heartbeat task to stop. The
        main tunnel connection manager remains responsible for deciding
        whether the tunnel should reconnect.
        """

        try:
            while self._running:
                #
                # Send ping
                #

                frame = make_frame(
                    MessageType.PING,
                )

                try:
                    await self.websocket.send(
                        json.dumps(frame),
                    )

                except asyncio.CancelledError:
                    raise

                except Exception as exc:
                    # A concurrent WebSocket shutdown is expected during
                    # normal tunnel teardown. Do not turn it into a
                    # user-facing error.
                    logger.debug(
                        "Heartbeat ping could not be sent: %s",
                        exc,
                    )

                    break

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
                        "Heartbeat timeout (%.1fs)",
                        elapsed,
                    )

                    self._running = False

                    await self._close_websocket()

                    break

                #
                # Wait before sending the next ping.
                #
                # asyncio.sleep() is cancellable, allowing stop() to
                # terminate the heartbeat promptly.
                #

                await asyncio.sleep(
                    self.interval,
                )

        except asyncio.CancelledError:
            # Normal during tunnel shutdown/reconnect.
            self._running = False
            raise

        except Exception as exc:
            self._running = False

            logger.debug(
                "Heartbeat stopped due to WebSocket error: %s",
                exc,
            )

        finally:
            self._running = False