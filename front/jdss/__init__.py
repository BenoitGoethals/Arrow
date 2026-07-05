"""Native, backend-independent JDSS gateway client for the Front desktop COP.

Lets Front talk to a JDSSArrow gateway *directly* (HTTP + WebSocket) without going
through the Arrow backend — for standalone / backend-down operation. When the Arrow
backend is up, its own JDSS bridge already relays JDSS data to Front, so this direct
path is an explicitly-connected, off-by-default mode to avoid duplication.
"""
