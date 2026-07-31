# borecli/bore/frames.py

import json
import logging
import time
import uuid

from websockets.exceptions import ConnectionClosed

from .protocol import (
    PROTOCOL_VERSION,
    MessageType,
)


logger = logging.getLogger(__name__)


# ============================================================
# Base Frame
# ============================================================


def make_frame(
    message_type,
    **payload,
):
    """
    Create a BoreHook protocol frame.
    """

    return {
        "protocol": PROTOCOL_VERSION,
        "frame_id": uuid.uuid4().hex,
        "timestamp": int(time.time() * 1000),
        "type": message_type,
        **payload,
    }



# ============================================================
# Tunnel Registration
# ============================================================


def make_tunnel_register(
    *,
    tunnel_id,
    client="borecli",
    version="1.0",
):

    return make_frame(

        MessageType.TUNNEL_REGISTER,

        tunnel_id=tunnel_id,

        client=client,

        version=version,

    )



# ============================================================
# HTTP Frames
# ============================================================


def make_http_request(
    **payload,
):

    return make_frame(

        MessageType.HTTP_REQUEST,

        **payload,

    )




def make_http_response(
    *,
    request_id,
    status,
    headers,
    body,
    binary=False,
):

    return make_frame(

        MessageType.HTTP_RESPONSE,

        request_id=request_id,

        status=status,

        headers=headers,

        body=body,

        binary=binary,

    )




def make_http_chunk(
    *,
    request_id,
    chunk_index,
    total_chunks,
    body,
    binary=False,
    status=None,
    headers=None,
):

    frame = make_frame(

        MessageType.HTTP_RESPONSE_CHUNK,

        request_id=request_id,

        chunk_index=chunk_index,

        total_chunks=total_chunks,

        body=body,

        binary=binary,

    )


    if status is not None:

        frame["status"] = status


    if headers is not None:

        frame["headers"] = headers


    return frame



# ============================================================
# WebSocket Frames
# ============================================================


def make_ws_connect(
    **payload,
):

    return make_frame(
        MessageType.WS_CONNECT,
        **payload,
    )



def make_ws_message(
    **payload,
):

    return make_frame(
        MessageType.WS_MESSAGE,
        **payload,
    )



def make_ws_close(
    **payload,
):

    return make_frame(
        MessageType.WS_CLOSE,
        **payload,
    )



# ============================================================
# Heartbeat
# ============================================================


def make_ping():

    return make_frame(
        MessageType.PING
    )



def make_pong():

    return make_frame(
        MessageType.PONG
    )



# ============================================================
# Errors / Metrics
# ============================================================


def make_error(
    message,
):

    return make_frame(

        MessageType.ERROR,

        message=message,

    )



def make_metrics(
    **payload,
):

    return make_frame(

        MessageType.METRICS,

        **payload,

    )



# ============================================================
# Transport
# ============================================================


async def send_frame(
    websocket,
    frame,
):

    """
    Send protocol frame.
    """

    payload = json.dumps(
        frame
    )

    await websocket.send(
        payload
    )



async def receive_frame(
    websocket,
):

    """
    Receive one protocol frame.
    """

    try:

        message = await websocket.recv()


    except ConnectionClosed:

        logger.warning(
            "WebSocket closed."
        )

        return None


    except Exception:

        logger.exception(
            "Receive frame failed."
        )

        return None



    if isinstance(
        message,
        bytes,
    ):

        message = message.decode(
            "utf-8"
        )



    try:

        frame = json.loads(
            message
        )


    except json.JSONDecodeError:

        logger.warning(
            "Invalid JSON received:"
            " %s",
            message,
        )

        return None



    if not isinstance(
        frame,
        dict,
    ):

        logger.warning(
            "Invalid frame type"
        )

        return None



    protocol = frame.get(
        "protocol"
    )


    if protocol != PROTOCOL_VERSION:

        logger.warning(
            "Protocol mismatch:"
            " %s",
            protocol,
        )

        return None



    if "type" not in frame:

        logger.warning(
            "Frame missing type"
        )

        return None



    return frame