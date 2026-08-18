"""Scientific projection operations."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def maximum_intensity_projection(stack_zyx: NDArray[np.generic]) -> NDArray[np.generic]:
    """Project a non-empty Z/Y/X stack along Z without changing its dtype."""

    if stack_zyx.ndim != 3 or stack_zyx.shape[0] == 0:
        raise ValueError("Maximum projection requires a non-empty Z/Y/X stack.")
    return np.max(stack_zyx, axis=0)
