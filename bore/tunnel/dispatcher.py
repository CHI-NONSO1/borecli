# borecli/bore/tunnel/dispatcher.py

import logging

from bore.protocol import (
    PROTOCOL_VERSION,
    MessageType,
)

from bore.frames import (
    send_frame,
    make_frame,
)

from bore.handlers.http_handler import (
    process_request,
)

from bore.handlers.websocket_handler import (
    handle_ws_connect,
    handle_ws_message,
    handle_ws_close,
)


logger = logging.getLogger(__name__)


class MessageDispatcher:
    """
    Routes BoreHook protocol frames.

    The dispatcher does NOT:
    - open connections
    - forward HTTP
    - manage websockets

    It only decides who handles each frame.
    """

    def __init__(
        self,
        websocket,
        local_port,
        heartbeat,
    ):

        self.websocket = websocket

        self.local_port = local_port

        self.heartbeat = heartbeat


    async def dispatch(
        self,
        frame: dict,
    ):

        #
        # Validate protocol
        #

        protocol = frame.get(
            "protocol"
        )

        if protocol != PROTOCOL_VERSION:

            logger.warning(
                "Unsupported protocol: %s",
                protocol,
            )

            return


        message_type = frame.get(
            "type"
        )


        if not message_type:

            logger.warning(
                "Frame missing type"
            )

            return


        logger.debug(
            "Dispatching %s",
            message_type,
        )


        #
        # -----------------------------
        # HTTP
        # -----------------------------
        #

        # if message_type == MessageType.HTTP_REQUEST:


        #     await process_request(

        #         websocket=self.websocket,

        #         local_port=self.local_port,

        #         frame=frame,

        #     )

        #     return
        
        if message_type == MessageType.HTTP_REQUEST:
            try:
                await process_request(
                    websocket=self.websocket,
                    local_port=self.local_port,
                    frame=frame,
                )
            except Exception:
                logger.exception("Failed to process HTTP request")
            return



        #
        # -----------------------------
        # WebSocket
        # -----------------------------
        #

        if message_type == MessageType.WS_CONNECT:


            await handle_ws_connect(

                websocket=self.websocket,

                local_port=self.local_port,

                frame=frame,

            )

            return



        if message_type == MessageType.WS_MESSAGE:


            await handle_ws_message(

                frame=frame,

            )

            return



        if message_type == MessageType.WS_CLOSE:


            await handle_ws_close(

                frame=frame,

            )

            return



        #
        # -----------------------------
        # Heartbeat
        # -----------------------------
        #

        if message_type == MessageType.PING:


            await send_frame(

                self.websocket,

                make_frame(

                    MessageType.PONG

                )

            )

            return



        if message_type == MessageType.PONG:


            if self.heartbeat:

                self.heartbeat.pong()


            return



        #
        # -----------------------------
        # Server messages
        # -----------------------------
        #

        if message_type == MessageType.ERROR:


            logger.error(

                "Server error: %s",

                frame.get(
                    "message",
                    "Unknown error",
                )

            )

            return



        if message_type == MessageType.TUNNEL_STATUS:


            logger.info(

                "Tunnel status: %s",

                frame.get(
                    "status"
                )

            )

            return



        if message_type == MessageType.METRICS:


            logger.debug(
                "Metrics received: %s",
                frame,
            )

            return



        logger.warning(

            "Unknown message type: %s",

            message_type,

        )