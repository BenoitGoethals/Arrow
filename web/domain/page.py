"""Domain model for a rendered page.

A PageView is a template name + the context the template needs. It carries
no Flask types; it can be built and asserted on in pure unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PageView:
    template: str
    context: dict[str, Any] = field(default_factory=dict)
