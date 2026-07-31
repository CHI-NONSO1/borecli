# borecli/bore/websocket_client.py

import base64
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import requests
import websocket

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_WORKERS = 20
MAX_RESPONSE_BYTES = 50 * 1024 * 1024
CHUNK_SIZE = 512 * 1024

SESSION = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    pool_connections=DEFAULT_WORKERS,
    pool_maxsize=DEFAULT_WORKERS,
)
SESSION.mount("http://", adapter)
SESSION.mount("https://", adapter)

SEND_LOCK = threading.Lock()

EXCLUDED_REQUEST_HEADERS = {
    "host", "connection", "keep-alive",
    "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding",
    "upgrade", "content-length", "accept-encoding",
}


def is_binary_content(content_type):
    if not content_type:
        return True
    content_type = content_type.lower()
    text_types = (
        "text/",
        "application/json",
        "application/javascript",
        "application/x-javascript",
        "application/xml",
        "application/xhtml+xml",
        "application/graphql",
        "application/ld+json",
        "application/problem+json",
        "image/svg+xml",
    )
    return not any(content_type.startswith(p) for p in text_types)


def handle_request(local_port, data):
    method = data.get("method", "GET")
    path = data.get("path", "/")
    body = data.get("body", "")
    request_binary = data.get("binary", False)

    #
    # Decode request body received from BoreHook.
    #
    if request_binary:
        body = base64.b64decode(body)
    else:
        if isinstance(body, str):
            body = body.encode("utf-8")
    request_id = data.get("request_id")
    incoming_headers = dict(data.get("headers", {}))

    headers = {
        k: v for k, v in incoming_headers.items()
        if k.lower() not in EXCLUDED_REQUEST_HEADERS
    }

    url = f"http://127.0.0.1:{local_port}{path}"
    logger.info("Incoming %s %s", method, path)

    try:
        response = SESSION.request(
            method=method,
            url=url,
            headers=headers,
            data=body,
            allow_redirects=False,
            timeout=(5, 120),
            stream=True,
        )

        response_headers = dict(response.headers)
        response_headers.pop("Content-Encoding", None)
        response_headers.pop("Transfer-Encoding", None)
        response_headers.pop("Content-Length", None)

        content_type = response_headers.get("Content-Type", "")
        binary = is_binary_content(content_type)

        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if chunk:
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    logger.warning("Response for %s exceeded %d bytes, truncating.", path, MAX_RESPONSE_BYTES)
                    break
                chunks.append(chunk)
        raw = b"".join(chunks)

        logger.info("Completed %s %s -> %s (%d bytes)", method, path, response.status_code, total)

        return {
            "request_id": request_id,
            "status": response.status_code,
            "headers": response_headers,
            "raw": raw,
            "binary": binary,
        }

    except requests.Timeout:
        logger.error("Timeout forwarding %s %s", method, path)
        return {
            "request_id": request_id,
            "status": 504,
            "headers": {"Content-Type": "text/plain; charset=utf-8"},
            "raw": b"Tunnel timeout",
            "binary": False,
        }
    except requests.RequestException:
        logger.exception("Error forwarding request.")
        return {
            "request_id": request_id,
            "status": 502,
            "headers": {"Content-Type": "text/plain; charset=utf-8"},
            "raw": b"Unable to reach local application.",
            "binary": False,
        }
    except Exception:
        logger.exception("Unexpected forwarding error.")
        return {
            "request_id": request_id,
            "status": 500,
            "headers": {"Content-Type": "text/plain; charset=utf-8"},
            "raw": b"Internal tunnel error.",
            "binary": False,
        }


def send_response(ws, result):
    request_id = result["request_id"]
    binary = result["binary"]
    raw = result["raw"]

    if binary:
        encoded = base64.b64encode(raw).decode("ascii")
        body_bytes = encoded.encode("ascii")
    else:
        encoded = raw.decode("utf-8", errors="replace")
        body_bytes = encoded.encode("utf-8")

    total_size = len(body_bytes)

    if total_size <= CHUNK_SIZE:
        payload = json.dumps({
            "type": "response",
            "request_id": request_id,
            "status": result["status"],
            "headers": result["headers"],
            "body": encoded,
            "binary": binary,
        })
        with SEND_LOCK:
            ws.send(payload)
        return

    chunk_list = [
        body_bytes[i: i + CHUNK_SIZE]
        for i in range(0, total_size, CHUNK_SIZE)
    ]
    total_chunks = len(chunk_list)
    logger.info("Sending %s in %d chunks (%d bytes total)", request_id, total_chunks, total_size)

    for index, chunk in enumerate(chunk_list):
        chunk_body = chunk.decode("ascii" if binary else "utf-8")
        frame = {
            "type": "response_chunk",
            "request_id": request_id,
            "chunk_index": index,
            "total_chunks": total_chunks,
            "body": chunk_body,
            "binary": binary,
        }
        if index == 0:
            frame["status"] = result["status"]
            frame["headers"] = result["headers"]
        with SEND_LOCK:
            ws.send(json.dumps(frame))


def process_request(ws, local_port, data):
    request_id = data.get("request_id")
    try:
        result = handle_request(local_port, data)
        send_response(ws, result)
    except websocket.WebSocketConnectionClosedException:
        logger.warning("WebSocket closed while sending response for %s.", request_id)
    except BrokenPipeError:
        logger.warning("Broken pipe while sending response for %s.", request_id)
    except Exception as e:
        logger.error("Error processing request %s: %r", request_id, e)


def cleanup_futures(futures):
    completed = {f for f in futures if f.done()}
    for future in completed:
        try:
            future.result()
        except Exception:
            logger.exception("Worker raised an exception.")
    futures.difference_update(completed)


def run(
    ws_url,
    local_port,
    workers=DEFAULT_WORKERS,
    should_shutdown=lambda: False,
):
    assert isinstance(workers, int), f"workers must be int, got {type(workers)}"

    logger.info("Forwarding -> http://127.0.0.1:%s", local_port)
    logger.info("WebSocket  -> %s", ws_url)

    executor = ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="worker",
    )
    futures = set()

    def on_message(ws_app, message):
        logger.info("=" * 60)
        logger.info("RAW MESSAGE FROM SERVER")
        logger.info(message)
        logger.info("=" * 60)
        logger.info("Received WebSocket message:")
        logger.info(message)
        cleanup_futures(futures)
        if not message or should_shutdown():
            ws_app.close()
            return
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("Received invalid JSON.")
            return
        # if "request_id" not in data:
        #     return
        # future = executor.submit(process_request, ws_app, local_port, data)
        
        #
        # Only process HTTP forwarding messages.
        #\
# =============================================================
        logger.info(data.get("type"))
        if data.get("type") != "http.request":
        # if data.get("type") != "request":
            return
# =============================================================
        if "request_id" not in data:
            return

        future = executor.submit(
            process_request,
            ws_app,
            local_port,
            data,
        )
        futures.add(future)

    def on_error(ws_app, error):
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            ws_app.close()
            return
        logger.error("Tunnel error: %r", error)

    def on_close(ws_app, close_status_code, close_msg):
        logger.warning("Tunnel closed: %s - %s", close_status_code, close_msg)

    def on_open(ws_app):
        logger.info("Tunnel connected.")

    ws_app = websocket.WebSocketApp(
        ws_url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    # ------------------------------------------------------------------ #
    # Run run_forever in a daemon thread so the main thread stays free.   #
    # The signal handler calls ws_app.close() which stops the thread.     #
    # We then join with a timeout so we never block forever.              #
    # ------------------------------------------------------------------ #
    ws_thread = threading.Thread(
        target=ws_app.run_forever,
        kwargs={"ping_interval": 15, "ping_timeout": 5},
        daemon=True,  # dies automatically if the process exits
        name="ws-run-forever",
    )
    ws_thread.start()
    logger.info("Tunnel Connected Natively")

    # Block the caller here, but interruptibly — check the shutdown
    # flag every 0.2 s instead of sleeping inside run_forever.
    try:
        while ws_thread.is_alive():
            if should_shutdown():
                logger.info("Shutdown flag set — closing WebSocket.")
                ws_app.close()
                break
            ws_thread.join(timeout=0.2)
    finally:
        # Give the WS thread up to 3 s to finish its close handshake.
        ws_thread.join(timeout=3)

        logger.info("Waiting for %d active workers...", len(futures))
        for future in list(futures):
            try:
                future.result(timeout=2)
            except Exception:
                pass
        executor.shutdown(wait=False)
        logger.info("Tunnel closed.")