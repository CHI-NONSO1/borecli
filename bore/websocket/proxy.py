import asyncio
import contextlib
import logging
from typing import Awaitable, Callable, Optional

from websockets.exceptions import ConnectionClosed
from websockets.protocol import State

logger = logging.getLogger(__name__)


class WebSocketProxy:
    """
    Bidirectional websocket proxy.

    Relays websocket frames between two websocket connections while
    preserving text and binary frames.

    The proxy exits when either side disconnects.
    """

    def __init__(
        self,
        client_ws,
        local_ws,
        *,
        on_close: Optional[Callable[[], Awaitable[None]]] = None,
    ):
        self.client_ws = client_ws
        self.local_ws = local_ws
        self.on_close = on_close

        self._closed = False

    async def run(self):
        """
        Start bidirectional proxying.

        Returns when either websocket closes.
        """

        task1 = asyncio.create_task(
            self._pipe(
                self.client_ws,
                self.local_ws,
                "CLIENT",
                "LOCAL",
            )
        )

        task2 = asyncio.create_task(
            self._pipe(
                self.local_ws,
                self.client_ws,
                "LOCAL",
                "CLIENT",
            )
        )

        done, pending = await asyncio.wait(
            {task1, task2},
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()

        for task in pending:
            with contextlib.suppress(asyncio.CancelledError):
                await task

        await self.close()

    async def _pipe(
        self,
        source,
        destination,
        source_name: str,
        destination_name: str,
    ):
        """
        Forward websocket frames.
        """

        try:

            async for message in source:

                if isinstance(message, bytes):
                    logger.debug(
                        "%s → %s (%d bytes)",
                        source_name,
                        destination_name,
                        len(message),
                    )
                else:
                    logger.debug(
                        "%s → %s (%d chars)",
                        source_name,
                        destination_name,
                        len(message),
                    )

                # Preserve frame type automatically.
                await destination.send(message)

        except ConnectionClosed as exc:

            logger.info(
                "%s disconnected (%s)",
                source_name,
                exc.code,
            )

        except asyncio.CancelledError:
            raise

        except Exception:

            logger.exception(
                "Proxy error %s -> %s",
                source_name,
                destination_name,
            )

    async def close(self):

        if self._closed:
            return

        self._closed = True

        await self._close_socket(self.client_ws)
        await self._close_socket(self.local_ws)

        if self.on_close:
            await self.on_close()

    async def _close_socket(self, ws):

        try:

            if ws.state is not State.CLOSED:
                await ws.close()

        except Exception:
            pass