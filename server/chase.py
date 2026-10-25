"""Drive the live chase. One chunk at a time, then look again.

The phone server calls this while a round is open. A missing robot leaves the
round running and the robot still. A failed move marks the pose unknown and
ends the round as a draw. Between Bomba rounds, go_home drives the robot back
to the center and keeps the pose it tracked.
"""

import asyncio
import logging

from server.bridge import BridgeError, MoveResult
from server.lobby import LobbyBook
from server.planner import Chunk, home_chunk, mark_at, plan
from server.pose import Pose

log = logging.getLogger(__name__)

LOOK_AGAIN_SECONDS = 0.05


async def follow(book: LobbyBook, robot: object, code: str, on_pose=None, pose: Pose | None = None) -> None:
    """Chase the target until the round ends. A Bomba round passes the pose it kept."""
    pose = Pose() if pose is None else pose
    told_offline = False
    while book.pull_round_open(code):
        if not book.scoring_open(code):
            await asyncio.sleep(LOOK_AGAIN_SECONDS)
            continue
        rows = book.playing_marks(code)
        if rows is None:
            return
        target, marks, ids = _geometry(rows)
        decision = plan(pose, target, marks)
        if decision.arrived is not None:
            book.finish_arrival(code, ids[decision.arrived])
            log.info("lobby %s arrived at %s", code, ids[decision.arrived])
            return
        if book.clock_reached(code):
            if book.finish_if_due(code):
                log.info("lobby %s clock ended the chase", code)
                return
            await asyncio.sleep(LOOK_AGAIN_SECONDS)
            continue
        chunk = decision.chunk
        if chunk is None:
            await asyncio.sleep(LOOK_AGAIN_SECONDS)
            continue
        if not _online(robot):
            if not told_offline:
                log.info("lobby %s robot is offline, chase is holding still", code)
                told_offline = True
            await asyncio.sleep(LOOK_AGAIN_SECONDS)
            continue
        told_offline = False
        log.info("lobby %s %s %s %s", code, chunk.command, chunk.steps, chunk.direction)
        book.set_motion(code, True)
        retry = False
        try:
            try:
                result = await asyncio.to_thread(_dispatch, robot, chunk)
            except BridgeError as error:
                if error.message == "A move is already running.":
                    retry = True
                else:
                    pose.mark_unknown()
                    book.remember_pose(code, pose.x, pose.y, pose.heading, False)
                    book.finish_draw(code)
                    log.info("lobby %s drive failed: %s", code, error.message)
                    return
            else:
                if result.stopped or result.command is None:
                    pose.mark_unknown()
                    book.remember_pose(code, pose.x, pose.y, pose.heading, False)
                    book.finish_draw(code)
                    log.info("lobby %s move stopped before it finished", code)
                    return
                pose.apply(result.command, result.steps, result.direction)
                book.remember_pose(code, pose.x, pose.y, pose.heading, pose.known)
                log.info(
                    "lobby %s pose x=%.1f y=%.1f heading=%.1f",
                    code,
                    pose.x,
                    pose.y,
                    pose.heading,
                )
                if _declare_arrival(book, pose, code):
                    retry = False
                    break
        finally:
            book.set_motion(code, False)
        if on_pose is not None:
            await on_pose()
        if not book.pull_round_open(code):
            return
        if retry:
            await asyncio.sleep(LOOK_AGAIN_SECONDS)


async def go_home(book: LobbyBook, robot: object, code: str, pose: Pose, on_pose=None) -> None:
    """Drive back to the center between Bomba rounds. Offline, the robot stays put."""
    book.set_homing(code, _online(robot) and home_chunk(pose) is not None)
    try:
        while book.between_rounds(code):
            chunk = home_chunk(pose)
            if chunk is None or not _online(robot):
                return
            log.info("lobby %s home %s %s %s", code, chunk.command, chunk.steps, chunk.direction)
            try:
                result = await asyncio.to_thread(_dispatch, robot, chunk)
            except BridgeError as error:
                if error.message == "A move is already running.":
                    await asyncio.sleep(LOOK_AGAIN_SECONDS)
                    continue
                pose.mark_unknown()
                book.remember_pose(code, pose.x, pose.y, pose.heading, False)
                book.finish_draw(code)
                log.info("lobby %s drive home failed: %s", code, error.message)
                return
            if result.stopped or result.command is None:
                pose.mark_unknown()
                book.remember_pose(code, pose.x, pose.y, pose.heading, False)
                book.finish_draw(code)
                log.info("lobby %s move home stopped before it finished", code)
                return
            pose.apply(result.command, result.steps, result.direction)
            book.remember_pose(code, pose.x, pose.y, pose.heading, pose.known)
            if on_pose is not None:
                await on_pose()
    finally:
        book.set_homing(code, False)


def _declare_arrival(book: LobbyBook, pose: Pose, code: str) -> bool:
    """Name the reached player before the clock is allowed to finish the round."""
    rows = book.playing_marks(code)
    if rows is None:
        return False
    target, marks, ids = _geometry(rows)
    decision = plan(pose, target, marks)
    if decision.arrived is None:
        return False
    book.finish_arrival(code, ids[decision.arrived])
    log.info("lobby %s arrived at %s", code, ids[decision.arrived])
    return True


def _geometry(
    rows: list[tuple[str, float, bool]],
) -> tuple[tuple[float, float] | None, list[tuple[float, float]], list[str]]:
    target: tuple[float, float] | None = None
    marks: list[tuple[float, float]] = []
    ids: list[str] = []
    for player_id, angle, chased in rows:
        point = mark_at(angle)
        marks.append(point)
        ids.append(player_id)
        if chased:
            target = point
    return target, marks, ids


def _online(robot: object) -> bool:
    online = getattr(robot, "online", False)
    return bool(online)


def _dispatch(robot: object, chunk: Chunk) -> MoveResult:
    if chunk.command == "SPIN":
        return robot.spin(chunk.steps, chunk.direction)  # type: ignore[attr-defined]
    if chunk.command == "DRIVE":
        return robot.drive(chunk.steps, chunk.direction)  # type: ignore[attr-defined]
    raise BridgeError("The robot is offline.")
