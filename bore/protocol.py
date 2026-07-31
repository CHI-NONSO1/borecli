# borecli/bore/protocol.py


PROTOCOL_VERSION = "borehook/1.0"



class MessageType:
    """
    BoreHook tunnel protocol message types.
    """


    # =====================================================
    # Tunnel lifecycle
    # =====================================================

    TUNNEL_REGISTER = "tunnel.register"

    TUNNEL_STATUS = "tunnel.status"

    TUNNEL_CLOSE = "tunnel.close"



    # =====================================================
    # HTTP tunneling
    # =====================================================

    HTTP_REQUEST = "http.request"

    HTTP_RESPONSE = "http.response"

    HTTP_RESPONSE_CHUNK = (
        "http.response.chunk"
    )



    # =====================================================
    # WebSocket tunneling
    # =====================================================

    WS_CONNECT = "ws.connect"

    WS_CONNECTED = "ws.connected"

    WS_MESSAGE = "ws.message"

    WS_CLOSE = "ws.close"

    WS_ERROR = "ws.error"



    # =====================================================
    # Heartbeat
    # =====================================================

    PING = "ping"

    PONG = "pong"



    # =====================================================
    # System
    # =====================================================

    ERROR = "error"

    METRICS = "metrics"