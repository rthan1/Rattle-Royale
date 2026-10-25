"""Chase loop with a fake robot, so no Arduino is required."""

import asyncio
import json
import time
import unittest

from server.app import create_app, handle_text
from server.bridge import BridgeError, MoveResult
from server.chase import follow
from server.lobby import LobbyBook


def wake(book: LobbyBook, code: str) -> None:
    lobby = book._lobbies[code]
    now = time.time()
    lobby.opens_at = now - 1
    lobby.pull_at = now


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed = False

    async def send_str(self, data: str) -> None:
        self.sent.append(json.loads(data))


class FakeRobot:
    def __init__(self, book: LobbyBook | None = None, code: str | None = None) -> None:
        self.online = True
        self.commands: list[tuple[str, int, int]] = []
        self.book = book
        self.code = code
        self.fail = False
        self.expire_on_drive = False
        self.switch_to: str | None = None

    def spin(self, steps: int, direction: int) -> MoveResult:
        return self._move("SPIN", steps, direction)

    def drive(self, steps: int, direction: int) -> MoveResult:
        return self._move("DRIVE", steps, direction)

    def _move(self, command: str, steps: int, direction: int) -> MoveResult:
        self.commands.append((command, steps, direction))
        if self.fail:
            raise BridgeError("The robot disconnected.")
        if self.book is not None and self.code is not None and self.switch_to is not None:
            self.book.record_shakes(self.switch_to, 12)
            self.switch_to = None
        if self.expire_on_drive and command == "DRIVE":
            lobby = self.book._lobbies[self.code]  # type: ignore[union-attr]
            lobby.ends_at = 0
        if len(self.commands) > 80 and self.book is not None and self.code is not None:
            self.book._lobbies[self.code].ends_at = 0
        return MoveResult(False, command, steps, direction)


class ChaseTests(unittest.TestCase):
    def test_seat_zero_is_a_string_of_forward_drives_until_arrival(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        book.start(ada)
        wake(book, code)
        book.record_shakes(ada, 4)
        robot = FakeRobot()
        asyncio.run(follow(book, robot, code))
        snapshot = book.snapshot(code, ada)
        self.assertEqual(snapshot["reason"], "arrival")
        self.assertEqual(snapshot["winners"], ["Ada"])
        self.assertGreaterEqual(len(robot.commands), 1)
        self.assertTrue(all(command == "DRIVE" and direction == -1 for command, _, direction in robot.commands))
        self.assertGreater(snapshot["pose"]["x"], 120)
        self.assertTrue(snapshot["pose"]["known"])

    def test_the_opposite_player_is_a_string_of_reverse_drives(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        book.join(code, "Bea")
        book.start(ada)
        wake(book, code)
        bea = next(player_id for player_id in book.member_ids(code) if player_id != ada)
        book.record_shakes(bea, 4)
        robot = FakeRobot()
        asyncio.run(follow(book, robot, code))
        self.assertGreaterEqual(len(robot.commands), 1)
        self.assertTrue(all(command == "DRIVE" and direction == 1 for command, _, direction in robot.commands))
        self.assertEqual(book.snapshot(code, bea)["reason"], "arrival")
        self.assertEqual(book.snapshot(code, bea)["winners"], ["Bea"])

    def test_a_mark_inside_90_degrees_turns_before_it_drives(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        for name in ("Bea", "Cam", "Dee", "Eve"):
            book.join(code, name)
        book.start(ada)
        wake(book, code)
        bea = next(player_id for player_id in book.member_ids(code) if player_id != ada)
        book.record_shakes(bea, 4)
        robot = FakeRobot(book, code)
        robot.expire_on_drive = True
        asyncio.run(follow(book, robot, code))
        self.assertEqual(robot.commands[0][0], "SPIN")
        self.assertEqual(robot.commands[0][2], 1)
        self.assertGreater(sum(command == "SPIN" for command, _, _ in robot.commands), 1)
        self.assertEqual(robot.commands[-1][0], "DRIVE")
        self.assertEqual(robot.commands[-1][2], -1)

    def test_switching_to_the_opposite_player_reverses_on_the_next_chunk(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        book.join(code, "Bea")
        book.start(ada)
        wake(book, code)
        bea = next(player_id for player_id in book.member_ids(code) if player_id != ada)
        book.record_shakes(ada, 4)
        robot = FakeRobot(book, code)
        robot.switch_to = bea

        def drive(steps: int, direction: int) -> MoveResult:
            result = FakeRobot._move(robot, "DRIVE", steps, direction)
            if len(robot.commands) >= 2:
                robot.book._lobbies[code].ends_at = 0  # type: ignore[union-attr]
            return result

        robot.drive = drive  # type: ignore[method-assign]
        asyncio.run(follow(book, robot, code))
        self.assertEqual(robot.commands[0][0], "DRIVE")
        self.assertEqual(robot.commands[0][2], -1)
        self.assertEqual(robot.commands[1][0], "DRIVE")
        self.assertEqual(robot.commands[1][2], 1)
        self.assertEqual(book.snapshot(code, bea)["winners"], ["Ada", "Bea"])

    def test_the_clock_sends_nothing_once_it_has_already_run_out(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        bea, _ = book.join(code, "Bea")
        book.start(ada)
        wake(book, code)
        book.record_shakes(ada, 2)
        book.record_shakes(bea, 8)
        lobby = book._lobbies[code]
        lobby.players[1].shakes = 1
        lobby.ends_at = 0
        robot = FakeRobot()
        asyncio.run(follow(book, robot, code))
        self.assertEqual(robot.commands, [])
        snapshot = book.snapshot(code, ada)
        self.assertEqual(snapshot["reason"], "clock")
        self.assertEqual(snapshot["winners"], ["Ada", "Bea"])

    def test_an_offline_robot_still_names_the_chased_player(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        book.start(ada)
        wake(book, code)
        book.record_shakes(ada, 3)
        book._lobbies[code].ends_at = 0
        robot = FakeRobot()
        robot.online = False
        asyncio.run(follow(book, robot, code))
        self.assertEqual(robot.commands, [])
        self.assertEqual(book.snapshot(code, ada)["winners"], ["Ada"])

    def test_a_dropped_cable_is_a_draw_and_stops_the_chase(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        book.start(ada)
        wake(book, code)
        book.record_shakes(ada, 3)
        robot = FakeRobot()
        robot.fail = True
        asyncio.run(follow(book, robot, code))
        snapshot = book.snapshot(code, ada)
        self.assertEqual(snapshot["reason"], "draw")
        self.assertEqual(snapshot["winners"], [])
        self.assertEqual(len(robot.commands), 1)

    def test_the_phone_round_sends_the_first_drive(self) -> None:
        asyncio.run(self._phone_round())

    async def _phone_round(self) -> None:
        app = create_app()
        real = app["bridge"]
        robot = FakeRobot()
        app["bridge"] = robot
        socket = FakeSocket()
        chase = None
        try:
            player = await handle_text(
                app,
                socket,
                None,
                json.dumps({"type": "create", "name": "Ada", "shaking": True}),
            )
            code = socket.sent[-1]["code"]
            await handle_text(app, socket, player, json.dumps({"type": "start"}))
            lobby = app["book"]._lobbies[code]
            now = time.time()
            lobby.opens_at = now - 1
            lobby.pull_at = now
            chase = app["chase_tasks"][code]
            await handle_text(app, socket, player, json.dumps({"type": "shakes", "total": 4}))
            await asyncio.wait_for(chase, 2)
            self.assertEqual(robot.commands[0][0], "DRIVE")
            self.assertEqual(robot.commands[0][2], -1)
            arrived = [message for message in socket.sent if message.get("reason") == "arrival"]
            self.assertTrue(arrived)
            self.assertGreater(arrived[-1]["pose"]["x"], 100)
            self.assertIn("mark_radius", arrived[-1])
        finally:
            if chase is not None and not chase.done():
                chase.cancel()
            pending = [
                task
                for name in ("round_tasks", "pull_tasks", "chase_tasks")
                for task in app.get(name, {}).values()
            ]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            real.close()


if __name__ == "__main__":
    unittest.main()
