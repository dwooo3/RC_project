"""JSON sanitisation for engine results.

The pricing services return rich dicts that mix numpy scalars/arrays, Enums,
dataclasses and a couple of audit objects. `jsonable` walks any such structure
and returns something `json`/Pydantic can encode losslessly (NaN/Inf collapse to
None, which is valid JSON, unlike the bare `NaN` token).
"""

from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

import numpy as np


# Heavy, non-serialisable objects the result dict carries for the desktop app;
# the bridge drops them — `calculation_id`/`inputs_hash` already capture the IDs.
_DROP_KEYS = {"audit_record", "calculation_record"}


def jsonable(obj: Any) -> Any:
    """Recursively convert an engine result into a JSON-safe structure."""
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, Enum):
        return jsonable(obj.value)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        v = float(obj)
        return v if math.isfinite(v) else None
    if isinstance(obj, (np.complexfloating, complex)):
        return {"re": jsonable(obj.real), "im": jsonable(obj.imag)}
    if isinstance(obj, np.ndarray):
        return [jsonable(x) for x in obj.tolist()]
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items() if k not in _DROP_KEYS}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(x) for x in obj]
    if is_dataclass(obj) and not isinstance(obj, type):
        return jsonable(asdict(obj))
    return str(obj)
