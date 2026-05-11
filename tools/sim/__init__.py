"""tools.sim — Arrow CoT Simulator sub-package.

Public API re-exported here for convenience::

    from tools.sim import SimFrame, registry, CotEntry, CotMessageProvider

Importing this package also imports ``providers``, which triggers all
``@register_provider`` decorators so the built-in catalogue is registered
before ``SimFrame`` is instantiated.
"""

from . import providers as _providers  # noqa: F401 — side-effect: registers built-ins

from .builder    import CotXmlBuilder
from .client     import BackendClient, WsMonitor
from .domain     import CotEntry
from .frame      import SimFrame
from .messages   import (
    MsgAutoStopped, MsgAutoTrigger, MsgLoginErr, MsgLoginOk,
    MsgSendErr, MsgSendOk, MsgWsBtn, MsgWsRaw, MsgWsStatus, QueueMsg,
)
from .providers  import JsonFileCotProvider
from .registry   import CotLibraryRegistry, CotMessageProvider, register_provider, registry
from .strategies import AutoSend, BurstSend, OnceSend, SendStrategy

__all__ = [
    # domain
    "CotEntry",
    # builder
    "CotXmlBuilder",
    # registry
    "CotLibraryRegistry", "CotMessageProvider", "register_provider", "registry",
    # providers
    "JsonFileCotProvider",
    # strategies
    "AutoSend", "BurstSend", "OnceSend", "SendStrategy",
    # client
    "BackendClient", "WsMonitor",
    # messages
    "MsgAutoStopped", "MsgAutoTrigger", "MsgLoginErr", "MsgLoginOk",
    "MsgSendErr", "MsgSendOk", "MsgWsBtn", "MsgWsRaw", "MsgWsStatus", "QueueMsg",
    # GUI
    "SimFrame",
]
