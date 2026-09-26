import asyncio
import logging
from contextlib import suppress

import websockets

from bore.frames import (
    receive_frame,
)
from bore.tunnel.dispatcher import MessageDispatcher
from bore.tunnel.heartbeat import Heartbeat

logger = logging.getLogger(__name__)


class TunnelClient:
    """
    BoreHook async tunnel client.

    Handles:

    - websocket lifecycle
    - protocol receive loop
    - dispatcher
    - heartbeat
    - reconnect
    - graceful shutdown

    The TunnelClient owns the lifecycle of the main BoreHook WebSocket.
    Heartbeat and dispatcher tasks must be stopped before the WebSocket
    itself is closed.
    """

    def __init__(
        self,
        *,
        ws_url: str,
        local_port: int,
        tunnel_id: str,
        reconnect_delay: int = 5,
    ):
        self.ws_url = ws_url
        self.local_port = local_port
        self.tunnel_id = tunnel_id
        self.reconnect_delay = reconnect_delay

        self.websocket = None
        self.heartbeat = None
        self.dispatcher = None

        self._shutdown = False

        self._tasks = set()

        # Prevent concurrent cleanup calls from racing over the same
        # heartbeat/WebSocket objects.
        self._cleanup_lock = asyncio.Lock()

    async def _safe_dispatch(self, frame):
        """
        Dispatch one frame without allowing dispatcher exceptions to
        terminate the main receive loop.
        """

        try:
            await self.dispatcher.dispatch(frame)

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "Dispatcher crashed",
            )

    async def start(
        self,
        should_shutdown=lambda: False,
    ):
        """
        Start the tunnel and reconnect until shutdown is requested.
        """

        while not self._shutdown:

            if should_shutdown():
                break

            try:
                await self._connect()

                await self._receive_loop(
                    should_shutdown,
                )

            except asyncio.CancelledError:
                break

            except Exception:
                logger.exception(
                    "Tunnel connection failed",
                )

            finally:
                await self._cleanup()

            if self._shutdown:
                break

            if should_shutdown():
                break

            logger.info(
                "Reconnecting in %s seconds",
                self.reconnect_delay,
            )

            #
            # Use short cancellable sleeps instead of one long sleep so
            # shutdown requests are handled promptly.
            #

            for _ in range(self.reconnect_delay * 10):

                if self._shutdown:
                    return

                if should_shutdown():
                    return

                await asyncio.sleep(0.1)

    async def stop(self):
        """
        Request tunnel shutdown.

        Cleanup owns WebSocket closure. This prevents stop() from closing
        the socket while heartbeat or dispatcher shutdown is still in
        progress.
        """

        self._shutdown = True

        await self._cleanup()

    async def _connect(self):
        """
        Establish the main BoreHook WebSocket and initialize the
        dispatcher and heartbeat.
        """

        logger.info(
            "Connecting %s",
            self.ws_url,
        )

        websocket = await websockets.connect(
            self.ws_url,
            ping_interval=None,
            max_size=None,
        )

        #
        # Assign the WebSocket only after the connection succeeds.
        #

        self.websocket = websocket

        logger.info(
            "Tunnel websocket connected",
        )

        #
        # Create heartbeat.
        #

        self.heartbeat = Heartbeat(
            self.websocket,
        )

        #
        # Create dispatcher.
        #

        self.dispatcher = MessageDispatcher(
            websocket=self.websocket,
            local_port=self.local_port,
            heartbeat=self.heartbeat,
        )

        #
        # Start heartbeat only after both the WebSocket and dispatcher
        # have been initialized.
        #

        await self.heartbeat.start()

    async def _receive_loop(
        self,
        should_shutdown,
    ):
        """
        Receive protocol frames from the BoreHook server.

        Dispatcher work is performed in independent tasks so that one
        slow frame handler does not block receipt of subsequent frames.
        """

        while True:

            if self._shutdown:
                break

            if should_shutdown():
                break

            websocket = self.websocket

            if websocket is None:
                break

            try:
                frame = await asyncio.wait_for(
                    receive_frame(websocket),
                    timeout=1,
                )

            except asyncio.TimeoutError:
                continue

            except asyncio.CancelledError:
                raise

            except Exception:
                #
                # A closed or failed tunnel connection should return
                # control to start(), which will perform cleanup and
                # reconnect.
                #
                logger.debug(
                    "Tunnel receive loop ended",
                    exc_info=True,
                )

                break

            if frame is None:
                break

            #
            # Do not create new dispatcher tasks once shutdown has begun.
            #

            if self._shutdown:
                break

            task = asyncio.create_task(
                self._safe_dispatch(frame),
                name="tunnel-dispatch",
            )

            self._tasks.add(task)

            task.add_done_callback(
                self._tasks.discard,
            )

    async def _cancel_dispatch_tasks(self):
        """
        Cancel and await all outstanding dispatcher tasks.
        """

        tasks = list(self._tasks)

        if not tasks:
            return

        for task in tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        self._tasks.clear()

    async def _cleanup(self):
        """
        Clean up the current tunnel connection safely.

        Shutdown order:

            1. Prevent new dispatcher work
            2. Cancel existing dispatcher tasks
            3. Stop heartbeat
            4. Close WebSocket
            5. Clear references

        This ordering prevents heartbeat/dispatcher tasks from racing
        against WebSocket closure.
        """

        async with self._cleanup_lock:

            #
            # Capture current objects locally.
            #
            # This prevents another cleanup step from observing partially
            # cleared state.
            #

            heartbeat = self.heartbeat
            websocket = self.websocket

            #
            # Stop accepting/processing additional dispatcher work.
            #

            await self._cancel_dispatch_tasks()

            #
            # Stop heartbeat BEFORE closing the WebSocket.
            #
            # The heartbeat may currently be sleeping, sending a ping,
            # or handling a timeout. Its own shutdown logic handles
            # cancellation safely.
            #

            if heartbeat is not None:

                with suppress(
                    asyncio.CancelledError,
                    Exception,
                ):
                    await heartbeat.stop()

            #
            # Close the main tunnel WebSocket.
            #

            if websocket is not None:

                try:
                    await websocket.close()

                except asyncio.CancelledError:
                    raise

                except Exception as exc:
                    #
                    # The peer may already have closed the connection.
                    # This is a normal shutdown race and does not need
                    # a traceback.
                    #
                    logger.debug(
                        "Tunnel websocket already closed during cleanup: %s",
                        exc,
                    )

            #
            # Only clear references after shutdown has completed.
            #

            if self.heartbeat is heartbeat:
                self.heartbeat = None

            if self.websocket is websocket:
                self.websocket = None

            self.dispatcher = None

            logger.info(
                "Tunnel connection cleaned up",
            )