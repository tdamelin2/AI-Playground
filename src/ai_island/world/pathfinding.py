"""A* on a grid of terrain costs."""

from __future__ import annotations

import heapq
from collections.abc import Sequence

Pos = tuple[int, int]

# Fixed neighbour order: right, down, left, up. Ties are broken by this order.
NEIGHBOURS: tuple[Pos, ...] = ((1, 0), (0, 1), (-1, 0), (0, -1))


def astar(costs: Sequence[Sequence[float | None]], start: Pos, goal: Pos) -> list[Pos] | None:
    """Lowest-cost path from ``start`` to ``goal`` (both included), or None.

    ``costs[y][x]`` is the cost of entering that tile; ``None`` means impassable. The start
    tile is not charged. Moves are to the 4 neighbours. The heuristic is the Manhattan
    distance times the smallest tile cost, which never overestimates.
    """
    height = len(costs)
    width = len(costs[0]) if height else 0

    def inside(p: Pos) -> bool:
        return 0 <= p[0] < width and 0 <= p[1] < height

    if not inside(start) or not inside(goal):
        return None
    if costs[goal[1]][goal[0]] is None or costs[start[1]][start[0]] is None:
        return None
    if start == goal:
        return [start]

    positive = [c for row in costs for c in row if c is not None]
    min_cost = min(positive)

    def h(p: Pos) -> float:
        return (abs(p[0] - goal[0]) + abs(p[1] - goal[1])) * min_cost

    best: dict[Pos, float] = {start: 0.0}
    came: dict[Pos, Pos] = {}
    counter = 0
    heap: list[tuple[float, float, int, Pos]] = [(h(start), 0.0, counter, start)]
    closed: set[Pos] = set()
    while heap:
        _, g, _, cur = heapq.heappop(heap)
        if cur in closed:
            continue
        if cur == goal:
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            path.reverse()
            return path
        closed.add(cur)
        for dx, dy in NEIGHBOURS:
            nxt = (cur[0] + dx, cur[1] + dy)
            if not inside(nxt):
                continue
            step = costs[nxt[1]][nxt[0]]
            if step is None or nxt in closed:
                continue
            ng = g + step
            if ng < best.get(nxt, float("inf")):
                best[nxt] = ng
                came[nxt] = cur
                counter += 1
                heapq.heappush(heap, (ng + h(nxt), ng, counter, nxt))
    return None
