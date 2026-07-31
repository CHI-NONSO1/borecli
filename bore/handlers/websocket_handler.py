
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


#
# Prevent concurrent websocket frame corruption
#
SEND_LOCK = asyncio.Lock()


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

                logger.debug(
                    "Relay shutdown failed.",exc_info=True
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

                pass



    async def shutdown(self):

        connections = list(
            self._connections.keys()
        )

        for connection_id in connections:

            await self.remove(
                connection_id
            )


#
# Global websocket manager
#

manager = WebSocketConnectionManager()

# ------------------------------------------------------------
# Connect localhost websocket
# ------------------------------------------------------------

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
            "Invalid ws.connect frame"
        )

        return


    #
    # Prevent duplicate connections
    #

    if manager.exists(connection_id):

        logger.warning(
            "Websocket already exists: %s",
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



    logger.info(
        "Connecting local websocket %s",
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

        logger.debug("Local websocket connection failed.", exc_info=True)

        click.secho(
            f"⚠️  Request received, but nothing is listening on "
            f"127.0.0.1:{local_port} — is your local app running?",
            fg="yellow",
        )


        async with SEND_LOCK:

            await send_frame(

                websocket,

                make_ws_close(

                    connection_id=connection_id,

                    code=1011,

                    reason=
                    "Unable to connect localhost websocket",

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

    async with SEND_LOCK:

        await send_frame(

            websocket,

            make_frame(

                MessageType.WS_CONNECTED,

                connection_id=connection_id,

            ),

        )



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


    logger.info(

        "Websocket connected: %s",

        connection_id,

    )
    
    # ------------------------------------------------------------
# Relay localhost websocket -> BoreHook server
# ------------------------------------------------------------

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

    logger.info(
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
            # Send safely
            #

            async with SEND_LOCK:

                await send_frame(

                    websocket,

                    frame,

                )



    except ConnectionClosed as exc:


        logger.info(

            "Local websocket closed %s (%s)",

            connection_id,

            exc.code,

        )


        async with SEND_LOCK:

            await send_frame(

                websocket,

                make_ws_close(

                    connection_id=connection_id,

                    code=exc.code,

                    reason=(
                        exc.reason
                        or ""
                    ),

                ),

            )



    except asyncio.CancelledError:


        logger.info(

            "Relay cancelled: %s",

            connection_id,

        )

        raise



    except Exception:
        logger.debug("Websocket relay failed.", exc_info=True)

        click.secho(
            f"⚠️  Websocket relay failed:{connection_id}",
            fg="yellow",
        )


        try:

            async with SEND_LOCK:

                await send_frame(

                    websocket,

                    make_ws_close(

                        connection_id=connection_id,

                        code=1011,

                        reason="Relay failure",

                    ),

                )

        except Exception:

            pass



    finally:


        await manager.remove(

            connection_id

        )


        logger.info(

            "Relay stopped: %s",

            connection_id,

        )
        # ------------------------------------------------------------
# Relay BoreHook server -> localhost websocket
# ------------------------------------------------------------

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
            "ws.message missing connection_id"
        )

        return



    #
    # Find local websocket
    #

    local_ws = manager.get(
        connection_id
    )


    if local_ws is None:

        logger.warning(

            "Unknown websocket connection: %s",

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


        logger.info(

            "Local websocket closed: %s",

            connection_id,

        )


        await manager.remove(

            connection_id

        )



    except Exception:
        logger.debug("Unable to forward websocket message.", exc_info=True)

        click.secho(
            f"⚠️  Unable to forward websocket message",
            fg="yellow",
        )


        await manager.remove(

            connection_id

        )
        
        # ------------------------------------------------------------
# Close localhost websocket
# ------------------------------------------------------------

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
            "ws.close missing connection_id"
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

            "Websocket already closed: %s",

            connection_id,

        )

        return



    logger.info(

        "Closing websocket %s (%s)",

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
        logger.debug("Failed closing local websocket.", exc_info=True)

        click.secho(
            f"⚠️  Request received, but "
            f"Failed closing local websocket",
            fg="yellow",
        )



    finally:


        await manager.remove(

            connection_id

        )


        logger.info(

            "Websocket removed: %s",

            connection_id,

        )
        
        # ------------------------------------------------------------
# Shutdown
# ------------------------------------------------------------

async def shutdown():
    """
    Close every active websocket connection.

    Called when TunnelClient stops.
    """

    logger.info(
        "Shutting down websocket handler..."
    )


    try:

        await manager.shutdown()


        logger.info(
            "All websocket connections closed."
        )


    except Exception:
        
        logger.debug("Websocket shutdown failed.", exc_info=True)

        click.secho(
            f"⚠️  Websocket shutdown failed",
            fg="yellow",
        )



# ------------------------------------------------------------
# Public exports
# ------------------------------------------------------------

__all__ = [

    "handle_ws_connect",

    "handle_ws_message",

    "handle_ws_close",

    "shutdown",

]