# borecli/bore/handlers/http_handler.py

import base64
import logging

import httpx
import click
from bore.frames import (
    make_http_response,
    make_http_chunk,
    send_frame,
)

from bore.handlers.error_pages import (
    tunnel_unreachable_page,
    tunnel_timeout_page,
    tunnel_internal_error_page,
)

logger = logging.getLogger(__name__)

#
# ------------------------------------------------------------
# Limits
# ------------------------------------------------------------
#


MAX_RESPONSE_BYTES = 50 * 1024 * 1024

CHUNK_SIZE = 512 * 1024

TIMEOUT = httpx.Timeout(
    connect=5,
    read=120,
    write=30,
    pool=30,
)

#
# ------------------------------------------------------------
# Shared HTTP Client
# ------------------------------------------------------------
#

CLIENT = httpx.AsyncClient(
    follow_redirects=False,
    timeout=TIMEOUT,
)

#
# ------------------------------------------------------------
# Request headers that must never be forwarded
# ------------------------------------------------------------
#

EXCLUDED_REQUEST_HEADERS = {

    "host",

    "connection",

    "keep-alive",

    "proxy-authenticate",

    "proxy-authorization",

    "te",

    "trailers",

    "transfer-encoding",

    "upgrade",

    "content-length",

    "accept-encoding",

}

TEXT_CONTENT_TYPES = (

    "text/",

    "application/json",

    "application/javascript",

    "application/x-javascript",

    "application/xml",

    "application/xhtml+xml",

    "application/graphql",

    "application/problem+json",

    "application/ld+json",

    "image/svg+xml",

)


def is_binary_content(
    content_type: str | None,
) -> bool:

    if not content_type:

        return True

    content_type = content_type.lower()

    return not any(

        content_type.startswith(prefix)

        for prefix in TEXT_CONTENT_TYPES

    )
    #
# ------------------------------------------------------------
# Forward one HTTP request to localhost
# ------------------------------------------------------------
#

async def forward_request(
    *,
    local_port: int,
    frame: dict,
) -> dict:
    """
    Forward a BoreHook HTTP request to the
    user's local application.
    """

    method = frame.get("method", "GET")

    path = frame.get("path", "/")

    query = frame.get("query_string", "")

    request_id = frame["request_id"]

    binary = frame.get("binary", False)

    body = frame.get("body", "")

    #
    # --------------------------------------------------------
    # Decode request body
    # --------------------------------------------------------
    #

    if binary:

        body = base64.b64decode(body)

    else:

        body = body.encode("utf-8")

    #
    # --------------------------------------------------------
    # Copy headers
    # --------------------------------------------------------
    #

    incoming_headers = frame.get("headers", {})

    headers = {

        key: value

        for key, value in incoming_headers.items()

        if key.lower() not in EXCLUDED_REQUEST_HEADERS

    }

    #
    # --------------------------------------------------------
    # Build localhost URL
    # --------------------------------------------------------
    #

    url = f"http://127.0.0.1:{local_port}{path}"

    if query:

        url += f"?{query}"

    logger.info(
        "%s %s",
        method,
        url,
    )

    try:

        response = await CLIENT.request(

            method=method,

            url=url,

            headers=headers,

            content=body,

        )

        #
        # ----------------------------------------------------
        # Remove hop-by-hop headers
        # ----------------------------------------------------
        #

        response_headers = dict(response.headers)

        response_headers.pop(
            "Transfer-Encoding",
            None,
        )

        response_headers.pop(
            "Content-Encoding",
            None,
        )

        response_headers.pop(
            "Content-Length",
            None,
        )

        raw = response.content

        if len(raw) > MAX_RESPONSE_BYTES:

            logger.warning(
                "Response exceeded %d bytes.",
                MAX_RESPONSE_BYTES,
            )

            raw = raw[:MAX_RESPONSE_BYTES]

        return {

            "request_id": request_id,

            "status": response.status_code,

            "headers": response_headers,

            "raw": raw,

            "binary": is_binary_content(

                response_headers.get(

                    "Content-Type",

                    "",

                )

            ),

        }

 
    except httpx.ConnectError:

        logger.debug("Unable to connect to localhost.", exc_info=True)

        click.secho(
            f"⚠️  Request received, but nothing is listening on "
            f"127.0.0.1:{local_port} — is your local app running?",
            fg="yellow",
        )

        return {
            "request_id": request_id,
            "status": 200,  
            "headers": {"Content-Type": "text/html; charset=utf-8"},
            "raw": tunnel_unreachable_page(local_port=local_port).encode("utf-8"),
            "binary": False,
        }

    except httpx.ReadTimeout:

        logger.debug("Local application timed out.", exc_info=True)

        click.secho(
            f"⚠️  Request to 127.0.0.1:{local_port} timed out.",
            fg="yellow",
        )

        return {
            "request_id": request_id,
            "status": 200,
            "headers": {"Content-Type": "text/html; charset=utf-8"},
            "raw": tunnel_timeout_page().encode("utf-8"),
            "binary": False,
        }

    except Exception:

        logger.debug("Local application timed out.", exc_info=True)

        click.secho(
            f"⚠️  Request to 127.0.0.1:{local_port} timed out.",
            fg="yellow",
        )

        return {
            "request_id": request_id,
            "status": 200,
            "headers": {"Content-Type": "text/html; charset=utf-8"},
            "raw": tunnel_internal_error_page().encode("utf-8"),
            "binary": False,
        }
        
        #
# ------------------------------------------------------------
# Encode response body
# ------------------------------------------------------------
#

def encode_response_body(
    raw: bytes,
    binary: bool,
) -> tuple[str, bytes]:

    """
    Convert raw response bytes into a string suitable
    for transmission over the BoreHook protocol.

    Returns

        encoded_body
        encoded_bytes
    """

    if binary:

        encoded = base64.b64encode(
            raw,
        ).decode("ascii")

        encoded_bytes = encoded.encode(
            "ascii",
        )

    else:

        encoded = raw.decode(
            "utf-8",
            errors="replace",
        )

        encoded_bytes = encoded.encode(
            "utf-8",
        )

    return encoded, encoded_bytes


#
# ------------------------------------------------------------
# Split encoded payload into protocol chunks
# ------------------------------------------------------------
#

def split_into_chunks(
    encoded_bytes: bytes,
):

    """
    Yield encoded payload chunks.

    This generator is used for large HTTP responses.
    """

    for offset in range(

        0,

        len(encoded_bytes),

        CHUNK_SIZE,

    ):

        yield encoded_bytes[
            offset:
            offset + CHUNK_SIZE
        ]


#
# ------------------------------------------------------------
# Build protocol frames
# ------------------------------------------------------------
#

def build_response_frames(
    result: dict,
):

    """
    Convert a forwarded HTTP response into one or more
    BoreHook protocol frames.
    """

    body, body_bytes = encode_response_body(

        result["raw"],

        result["binary"],

    )

    #
    # Small response
    #

    if len(body_bytes) <= CHUNK_SIZE:

        yield make_http_response(

            request_id=result["request_id"],

            status=result["status"],

            headers=result["headers"],

            body=body,

            binary=result["binary"],

        )

        return

    #
    # Chunked response
    #

    chunks = list(

        split_into_chunks(
            body_bytes,
        )

    )

    total = len(chunks)

    logger.info(

        "Sending %s in %d chunks.",

        result["request_id"],

        total,

    )

    for index, chunk in enumerate(chunks):

        frame = make_http_chunk(

            request_id=result["request_id"],

            chunk_index=index,

            total_chunks=total,

            body=chunk.decode(

                "ascii"

                if result["binary"]

                else "utf-8"

            ),

            binary=result["binary"],

        )

        #
        # Metadata only on first chunk
        #

        if index == 0:

            frame["status"] = result["status"]

            frame["headers"] = result["headers"]

        yield frame
        
        #
# ------------------------------------------------------------
# Send one HTTP response
# ------------------------------------------------------------
#

async def send_response(
    websocket,
    result: dict,
) -> None:
    """
    Send a forwarded HTTP response back to
    the BoreHook server.
    """

    request_id = result["request_id"]

    try:

        for frame in build_response_frames(result):

            await send_frame(
                websocket,
                frame,
            )

        logger.info(
            "Response sent (%s)",
            request_id,
        )

    except Exception:

        logger.exception(
            "Failed sending response %s",
            request_id,
        )

        raise
    
    #
# ------------------------------------------------------------
# Public API
# ------------------------------------------------------------
#

async def process_request(
    *,
    websocket,
    local_port: int,
    frame: dict,
) -> None:
    """
    Process one HTTP request received from the
    BoreHook server.

    Workflow

        Server
            │
            ▼
        forward_request()
            │
            ▼
        build_response_frames()
            │
            ▼
        send_response()
    """

    request_id = frame.get("request_id")

    logger.info(
        "Processing HTTP request %s",
        request_id,
    )

    try:

        #
        # Forward request to localhost
        #

        result = await forward_request(

            local_port=local_port,

            frame=frame,

        )

        #
        # Send response back to BoreHook
        #

        await send_response(

            websocket,

            result,

        )

        logger.info(
            "Completed HTTP request %s",
            request_id,
        )

    except Exception:

        logger.exception(

            "HTTP request failed (%s)",

            request_id,

        )

        #
        # Last-resort error response
        #

        fallback = {

            "request_id": request_id,

            "status": 500,

            "headers": {

                "Content-Type":
                    "text/plain; charset=utf-8",

            },

            "raw": b"Internal BoreHook tunnel error.",

            "binary": False,

        }

        try:

            await send_response(

                websocket,

                fallback,

            )

        except Exception:

            logger.exception(

                "Unable to send fallback response.",

            )
            
            #
# ------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------
#

async def shutdown() -> None:
    """
    Shutdown the shared HTTP client.

    Called when the BoreHook tunnel client exits.
    """

    try:

        await CLIENT.aclose()

        logger.info(
            "HTTP client closed."
        )

    except Exception:

        logger.exception(
            "Failed closing HTTP client."
        )