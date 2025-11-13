import math
from typing import List, Dict

import numpy as np

from models import Hook

#Safety threshold to clear from line
SAFETY_LIMIT = 90
RADAR_SPACING = 100.0  # metres between the two radars along the ship
DEFAULT_ANGLE = 0


def calculate_orientation_from_two_radars(berth) -> float:
    """
    Calculate ship orientation using exactly 2 radar readings.

    Assumptions:
    - We use the first and last ACTIVE radars in berth.radars
    - Distance between those two radars along the ship = 100m
    - 0 rad  = parallel to quay
    - >0 rad = second radar further from quay than first
    """

    # Pick active radars with a valid distance
    active_radars = [
        r for r in berth.radars
        if r.distanceStatus == "ACTIVE" and r.shipDistance is not None
    ]

    # Need at least 2, otherwise fall back
    if len(active_radars) < 2:
        return DEFAULT_ANGLE

    # Use exactly two: first and last active
    r1 = active_radars[0]
    r2 = active_radars[-1]

    d1 = r1.shipDistance
    d2 = r2.shipDistance

    # θ = atan2(Δdistance, along-ship spacing)
    angle = math.atan2(d2 - d1, RADAR_SPACING)
    return angle

def compute_hook_colours_for_berth(berth) -> Dict[tuple, str]:
    """
    Compute a colour for each hook in a berth based on:
    - all hooks in each bollard (group = bollard)
    - ship orientation angle from 2 radars (distance 100m)
    - same logic as your standalone colour script

    Returns:
        colours: dict[(berth_name, hook_name)] = 'red' | 'green' | 'yellow' | 'black'
    """
    angle = calculate_orientation_from_two_radars(berth)
    ANGLE_THRESH = math.pi / 180  # 1 degree

    groups: List[List[float]] = []      # list of tension lists
    group_hooks: List[List[Hook]] = []  # parallel list of hook lists

    # Build groups: each bollard → one group with ALL its hooks
    for bollard in berth.bollards:
        hooks = bollard.hooks
        if not hooks:
            continue

        tensions = []
        for hook in hooks:
            if hook.tension is None or hook.faulted:
                t = 0.0
            else:
                t = float(hook.tension)
            tensions.append(t)

        groups.append(tensions)
        group_hooks.append(hooks)

    if not groups:
        return {}

    num_groups = len(groups)
    colours: Dict[tuple, str] = {}

    for group_idx, (group, hooks) in enumerate(zip(groups, group_hooks), start=1):
        arr = np.array(group, dtype=float)
        stdev = float(np.std(arr))
        mean = float(np.mean(arr))


        group_desired: List[float] = []
        alarm = False

        # First half of bollards = "back", second half = "front"
        is_back_group = group_idx <= num_groups / 2

        for line in group:
            desiredLine = 0.0

            # Equalise within group if spread is large
            if stdev > 10:
                desiredLine -= line - mean

            # Angle contribution with back/front reversal
            if angle > ANGLE_THRESH:
                # bow further from quay than stern
                desiredLine += -5 if is_back_group else 5
            elif angle < -ANGLE_THRESH:
                # bow closer to quay than stern
                desiredLine += 5 if is_back_group else -5

            # Clamp so we don't exceed safety
            if desiredLine > SAFETY_LIMIT - line:
                desiredLine = SAFETY_LIMIT - line

            # Alarm if any line already above safety
            if line > SAFETY_LIMIT:
                alarm = True

            group_desired.append(desiredLine)

        # If any rope is unsafe, whole group is black, desired = 0
        if alarm:
            for hook in hooks:
                colours[(berth.name, hook.name)] = "black"
            continue

        # Otherwise, red / yellow / green per hook
        for hook, d in zip(hooks, group_desired):
            if d > 1.5:
                colour = "red"
            elif d < -1.5:
                colour = "green"
            else:
                colour = "yellow"

            colours[(berth.name, hook.name)] = colour

    return colours
