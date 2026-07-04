"""JDSSArrow coalition-gateway bridge.

Connects Arrow to an external JDSSArrow gateway (NATO AEP-76 / STANAG-4677) over
its HTTP + WebSocket API. Inbound: JDSS coalition messages (presence, contacts,
chat, casevac) are rendered onto the Arrow tactical map. Outbound: Arrow operator
GPS, tactical objects and chat are published into the JDSS network.
"""
