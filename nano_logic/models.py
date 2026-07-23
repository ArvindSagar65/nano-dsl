# nano_logic/models.py
from dataclasses import dataclass
from typing import Optional

@dataclass
class Rule:
    metric: str
    operator: str
    threshold: float
    action: str
    id: int = 0
    name: Optional[str] = None

@dataclass
class StopRule:
    identifier: str
