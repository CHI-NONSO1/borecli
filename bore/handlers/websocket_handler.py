# borecli/bore/handlers/websocket_handler.py

import asyncio
import base64
import logging

import click
import websockets
from websockets.exceptions import ConnectionClosed

from bore.frames import (
    make_frame,
    make_ws_message,
    make_ws_close,
    send_frame,
)
from bore.protocol import MessageType


logger = logging.getLogger(__name__)


# ============================================================
# Prevent concurrent websocket frame corruption
# ============================================================

SEND_LOCK = asyncio.Lock()


# ============================================================
# Safe BoreHook websocket sender
# ============================================================

async def safe_send_frame(
    websocket,
    frame,
):
    """
    Safely send a frame to the BoreHook websocket.

    A relay task can still be processing a message when the
    BoreHook websocket closes. In that situation, attempting
    to send another frame raises ConnectionClosed.

    This helper treats that condition as normal connection
    teardown instead of allowing it to become an unhandled
    task exception.
    """

    try:

        async with SEND_LOCK:

            await send_frame(
                websocket,
                frame,
            )

        return True

    except ConnectionClosed:

        logger.debug(
            "BoreHook websocket closed while sending frame."
        )

        return False

    except Exception:

        logger.exception(
            "Failed to send websocket frame."
        )

        return False


# ============================================================
# WebSocket connection manager
# ============================================================

class WebSocketConnectionManager:
    """
    Maintains active localhost websocket connections.

    connection_id:
        BoreHook websocket identifier

    websocket:
        Local application websocket
    """

    def __init__(self):

        self._connections = {}

        self._relay_tasks = {}

    def get(
        self,
        connection_id,
    ):

        return self._connections.get(
            connection_id
        )

    def exists(
        self,
        connection_id,
    ):

        return connection_id in self._connections

    def register(
        self,
        connection_id,
        websocket,
    ):

        self._connections[
            connection_id
        ] = websocket

    def register_task(
        self,
        connection_id,
        task,
    ):

        self._relay_tasks[
            connection_id
        ] = task

    async def remove(
        self,
        connection_id,
    ):

        #
        # Stop relay task
        #

        task = self._relay_tasks.pop(
            connection_id,
            None,
        )

        if (
            task
            and task != asyncio.current_task()
        ):

            task.cancel()

            try:

                await task

            except asyncio.CancelledError:

                pass

            except Exception:

                logger.exception(
                    "Relay shutdown failed."
                )

        #
        # Close local websocket
        #

        websocket = self._connections.pop(
            connection_id,
            None,
        )

        if websocket:

            try:

                await websocket.close()

            except Exception:

                logger.debug(
                    "Local websocket was already closed.",
                    exc_info=True,
                )

    async def shutdown(self):

        connections = list(
            self._connections.keys()
        )

        for connection_id in connections:

            await self.remove(
                connection_id
            )


# ============================================================
# Global websocket manager
# ============================================================

manager = WebSocketConnectionManager()


# ============================================================
# Connect localhost websocket
# ============================================================

async def handle_ws_connect(
    *,
    websocket,
    local_port,
    frame,
):
    """
    Handle ws.connect frame from BoreHook server.

    Creates a websocket connection to the user's
    local websocket application.
    """

    connection_id = frame.get(
        "connection_id"
    )

    path = frame.get(
        "path",
        "/",
    )

    query = frame.get(
        "query",
        "",
    )

    if not connection_id or not local_port:

        logger.error(
            "Invalid ws.connect frame."
        )

        return

    #
    # Prevent duplicate connections
    #

    if manager.exists(connection_id):

        logger.warning(
            "Websocket connection already exists: %s",
            connection_id,
        )

        return

    #
    # Build localhost websocket URL
    #

    url = (
        f"ws://127.0.0.1:"
        f"{local_port}"
        f"{path}"
    )

    if query:

        url += f"?{query}"

    #
    # Copy safe headers
    #

    incoming_headers = frame.get(
        "headers",
        {},
    )

    excluded_headers = {

        "host",
        "connection",
        "upgrade",
        "origin",
        "sec-websocket-key",
        "sec-websocket-version",
        "sec-websocket-extensions",
        "sec-websocket-protocol",

    }

    headers = [

        (
            key,
            value,
        )

        for key, value in incoming_headers.items()

        if key.lower()
        not in excluded_headers

    ]

    #
    # Rewrite local headers
    #

    headers.append(
        (
            "Host",
            f"127.0.0.1:{local_port}",
        )
    )

    headers.append(
        (
            "Origin",
            f"http://127.0.0.1:{local_port}",
        )
    )

    logger.debug(
        "Connecting local websocket: %s",
        url,
    )

    #
    # Connect to local websocket server
    #

    try:

        local_ws = await websockets.connect(

            url,

            additional_headers=headers,

            ping_interval=None,

            max_size=None,

        )

    except Exception:

        logger.exception(
            "Unable to connect to local websocket."
        )

        click.secho(
            "⚠️  Unable to connect to your local application. "
            "Make sure it is running and accepting WebSocket connections.",
            fg="yellow",
        )

        await safe_send_frame(

            websocket,

            make_ws_close(

                connection_id=connection_id,

                code=1011,

                reason="Unable to connect localhost websocket",

            ),

        )

        return

    #
    # Register connection
    #

    manager.register(

        connection_id,

        local_ws,

    )

    #
    # Tell server websocket is ready
    #

    connected = await safe_send_frame(

        websocket,

        make_frame(

            MessageType.WS_CONNECTED,

            connection_id=connection_id,

        ),

    )

    if not connected:

        await manager.remove(
            connection_id
        )

        return

    #
    # Start localhost -> BoreHook relay
    #

    relay_task = asyncio.create_task(

        relay_local_to_server(

            websocket=websocket,

            connection_id=connection_id,

            local_ws=local_ws,

        )

    )

    manager.register_task(

        connection_id,

        relay_task,

    )

    logger.debug(
        "Websocket connection established: %s",
        connection_id,
    )


# ============================================================
# Relay localhost websocket -> BoreHook server
# ============================================================

async def relay_local_to_server(
    *,
    websocket,
    connection_id,
    local_ws,
):
    """
    Forward websocket messages from the user's
    localhost application back to BoreHook.

    Direction:

        localhost websocket
                |
                |
                v
        BoreHook websocket
    """

    logger.debug(
        "Starting websocket relay: %s",
        connection_id,
    )

    try:

        async for message in local_ws:

            #
            # Binary websocket message
            #

            if isinstance(
                message,
                bytes,
            ):

                payload = (
                    base64.b64encode(
                        message
                    )
                    .decode("ascii")
                )

                frame = make_ws_message(

                    connection_id=connection_id,

                    binary=True,

                    body=payload,

                )

            #
            # Text websocket message
            #

            else:

                frame = make_ws_message(

                    connection_id=connection_id,

                    binary=False,

                    body=message,

                )

            #
            # Safely send to BoreHook.
            #
            # If the BoreHook websocket has already closed,
            # stop the relay without attempting another send.
            #

            sent = await safe_send_frame(

                websocket,

                frame,

            )

            if not sent:

                logger.debug(
                    "BoreHook websocket is closed; "
                    "stopping local websocket relay: %s",
                    connection_id,
                )

                break

    except ConnectionClosed as exc:

        logger.debug(
            "Local websocket closed: %s (code=%s)",
            connection_id,
            exc.code,
        )

    except asyncio.CancelledError:

        logger.debug(
            "Websocket relay cancelled: %s",
            connection_id,
        )

        raise

    except Exception:

        logger.exception(
            "Unexpected websocket relay failure: %s",
            connection_id,
        )

        #
        # Do not expose internal exception details to the user.
        #
        # The connection will be cleaned up in finally.
        #

    finally:

        await manager.remove(
            connection_id
        )

        logger.debug(
            "Websocket relay stopped: %s",
            connection_id,
        )


# ============================================================
# Relay BoreHook server -> localhost websocket
# ============================================================

async def handle_ws_message(
    *,
    frame,
):
    """
    Forward a websocket message received from
    BoreHook to the user's local websocket.

    Direction:

        BoreHook websocket
                |
                |
                v
        localhost websocket
    """

    connection_id = frame.get(
        "connection_id"
    )

    if not connection_id:

        logger.warning(
            "ws.message missing connection_id."
        )

        return

    #
    # Find local websocket
    #

    local_ws = manager.get(
        connection_id
    )

    if local_ws is None:

        #
        # A message may arrive after connection cleanup.
        # This is a normal shutdown race, so do not expose it
        # to the CLI user.
        #

        logger.debug(
            "Ignoring message for inactive websocket: %s",
            connection_id,
        )

        return

    binary = frame.get(
        "binary",
        False,
    )

    body = frame.get(
        "body",
        "",
    )

    try:

        #
        # Binary websocket frame
        #

        if binary:

            payload = base64.b64decode(
                body
            )

            await local_ws.send(
                payload
            )

        #
        # Text websocket frame
        #

        else:

            await local_ws.send(
                body
            )

        logger.debug(
            "Forwarded websocket message: %s",
            connection_id,
        )

    except ConnectionClosed:

        logger.debug(
            "Local websocket closed: %s",
            connection_id,
        )

        await manager.remove(
            connection_id
        )

    except Exception:

        logger.exception(
            "Unable to forward websocket message: %s",
            connection_id,
        )

        await manager.remove(
            connection_id
        )


# ============================================================
# Close localhost websocket
# ============================================================

async def handle_ws_close(
    *,
    frame,
):
    """
    Handle ws.close frame from BoreHook server.

    Direction:

        BoreHook
            |
            |
            v
        localhost websocket close
    """

    connection_id = frame.get(
        "connection_id"
    )

    if not connection_id:

        logger.warning(
            "ws.close missing connection_id."
        )

        return

    code = frame.get(
        "code",
        1000,
    )

    reason = frame.get(
        "reason",
        "",
    )

    local_ws = manager.get(
        connection_id
    )

    #
    # Already removed
    #

    if local_ws is None:

        logger.debug(
            "Websocket already removed: %s",
            connection_id,
        )

        return

    logger.debug(
        "Closing local websocket: %s (code=%s)",
        connection_id,
        code,
    )

    try:

        await local_ws.close(

            code=code,

            reason=reason,

        )

    except ConnectionClosed:

        pass

    except Exception:

        logger.exception(
            "Failed to close local websocket: %s",
            connection_id,
        )

    finally:

        await manager.remove(
            connection_id
        )

        logger.debug(
            "Websocket removed: %s",
            connection_id,
        )


# ============================================================
# Shutdown
# ============================================================

async def shutdown():
    """
    Close every active websocket connection.

    Called when TunnelClient stops.
    """

    logger.debug(
        "Shutting down websocket handler."
    )

    try:

        await manager.shutdown()

        logger.debug(
            "All websocket connections closed."
        )

    except Exception:

        logger.exception(
            "Websocket shutdown failed."
        )


# ============================================================
# Public exports
# ============================================================

__all__ = [

    "handle_ws_connect",

    "handle_ws_message",

    "handle_ws_close",

    "shutdown",

]