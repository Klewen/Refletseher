"""Temporal palette matching: keep colours on the same keyboard zone."""

from __future__ import annotations

from itertools import permutations

import numpy as np

_PERMS = np.array(list(permutations(range(4))), dtype=np.int64)  # 24 x 4


def best_assignment(previous: np.ndarray, new: np.ndarray, stickiness: float = 0.02) -> tuple[int, ...]:
    """Permutation ``p`` minimising sum_i dE(previous[i], new[p[i]]).

    Exhaustive over 4! = 24 permutations (exact Hungarian solution for 4x4).
    The identity is kept unless another assignment is better by more than
    ``stickiness`` (avoids swapping zones over insignificant differences).
    """
    prev = np.asarray(previous, dtype=np.float32)
    nw = np.asarray(new, dtype=np.float32)
    cost = np.linalg.norm(prev[:, None, :] - nw[None, :, :], axis=2)  # 4x4
    totals = cost[np.arange(4)[None, :], _PERMS].sum(axis=1)
    best = int(np.argmin(totals))
    identity_cost = float(totals[0])
    if identity_cost - float(totals[best]) <= stickiness:
        return (0, 1, 2, 3)
    return tuple(int(i) for i in _PERMS[best])
