"""One short move toward a floor mark. This module does not open a port.

The caller supplies the pose and a target. A reached mark is reported back
and no chunk is sent. The planner does not read shakes and does not talk to
the Arduino. Forward travel along the heading is ``DRIVE`` direction ``-1``.
Reverse travel is direction ``1``.
"""

import math
from dataclasses import dataclass

from server.pose import STEPS_PER_DEGREE, STEPS_PER_MM, Pose

MARK_RADIUS_MM = 152.4
ALIGN_DEGREES = 15.0
REVERSE_DEGREES = 90.0
MAX_SPIN_DEGREES = 5.0
MAX_DRIVE_MM = 30.0
ARRIVAL_RADIUS_MM = 25.0
HOME_RADIUS_MM = 10.0


@dataclass(frozen=True)
class Chunk:
    command: str
    steps: int
    direction: int


@dataclass(frozen=True)
class Plan:
    chunk: Chunk | None = None
    arrived: int | None = None


def mark_at(angle_degrees: float) -> tuple[float, float]:
    """A floor mark on the circle around home. Angle 0 is seat 0, on +x."""
    radians = math.radians(angle_degrees)
    return (MARK_RADIUS_MM * math.cos(radians), MARK_RADIUS_MM * math.sin(radians))


def choose_chunk(heading_error: float, distance_mm: float) -> Chunk | None:
    """Turn a heading error and a distance into one short ``SPIN`` or ``DRIVE``.

    An error inside 90° faces the mark and drives forward. An error of 90° or
    more turns until the tail points at the mark, then reverses toward it.
    """
    if abs(heading_error) < REVERSE_DEGREES:
        aim_error = heading_error
        drive_direction = -1
    else:
        aim_error = _signed_delta(heading_error + 180.0)
        drive_direction = 1
    if abs(aim_error) > ALIGN_DEGREES:
        turn = min(abs(aim_error), MAX_SPIN_DEGREES)
        direction = 1 if aim_error > 0 else -1
        return _chunk("SPIN", turn, STEPS_PER_DEGREE, direction)
    travel = min(max(distance_mm, 0.0), MAX_DRIVE_MM)
    return _chunk("DRIVE", travel, STEPS_PER_MM, drive_direction)


def plan(
    pose: Pose,
    target: tuple[float, float] | None,
    marks: list[tuple[float, float]] | None = None,
) -> Plan:
    """Arrival anywhere ends the chase. Otherwise return one chunk toward ``target``."""
    checked = marks if marks is not None else ([] if target is None else [target])
    arrived = arrived_mark(pose, checked)
    if arrived is not None:
        return Plan(arrived=arrived)
    return Plan(chunk=next_chunk(pose, target))


def next_chunk(pose: Pose, target: tuple[float, float] | None) -> Chunk | None:
    """The next chunk toward ``target``, or nothing if there is no move to send."""
    if target is None or not pose.known:
        return None
    distance = math.hypot(target[0] - pose.x, target[1] - pose.y)
    if distance <= ARRIVAL_RADIUS_MM:
        return None
    bearing = _bearing(pose.x, pose.y, target[0], target[1])
    return choose_chunk(_signed_error(pose.heading, bearing), distance)


def home_chunk(pose: Pose) -> Chunk | None:
    """The next chunk back to the center, or nothing once the robot is within ``HOME_RADIUS_MM``."""
    if not pose.known:
        return None
    distance = math.hypot(pose.x, pose.y)
    if distance <= HOME_RADIUS_MM:
        return None
    bearing = _bearing(pose.x, pose.y, 0.0, 0.0)
    return choose_chunk(_signed_error(pose.heading, bearing), distance)


def arrived_mark(pose: Pose, marks: list[tuple[float, float]]) -> int | None:
    """The closest mark inside the arrival radius. Unknown poses do not arrive."""
    if not pose.known:
        return None
    closest: int | None = None
    closest_distance = ARRIVAL_RADIUS_MM
    for index, (mark_x, mark_y) in enumerate(marks):
        distance = math.hypot(mark_x - pose.x, mark_y - pose.y)
        if distance > ARRIVAL_RADIUS_MM:
            continue
        if closest is None or distance < closest_distance:
            closest = index
            closest_distance = distance
    return closest


def _chunk(command: str, amount: float, scale: float, direction: int) -> Chunk | None:
    steps = int(round(amount * scale))
    if steps < 1:
        return None
    return Chunk(command, steps, direction)


def _bearing(x: float, y: float, target_x: float, target_y: float) -> float:
    degrees = math.degrees(math.atan2(target_y - y, target_x - x)) % 360.0
    if degrees == 0.0:
        return 0.0
    return degrees


def _signed_error(heading: float, bearing: float) -> float:
    return _signed_delta(bearing - heading)


def _signed_delta(degrees: float) -> float:
    error = degrees % 360.0
    if error > 180.0:
        error -= 360.0
    if error == 0.0:
        return 0.0
    return error
