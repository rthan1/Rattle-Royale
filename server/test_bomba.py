"""Bomba: the robot hunts the weakest shaker, and rounds knock players out."""

import asyncio
import json
import math
import time
import unittest
from unittest import mock

from server.app import create_app, handle_text
from server.lobby import LobbyBook, LobbyError
from server.planner import HOME_RADIUS_MM, home_chunk
from server.pose import Pose
from server.test_chase import FakeRobot, FakeSocket
from server.test_pull import players, wake


def lowest_seat_first(survivors: list) -> object:
    """Stand-in for the random first target, so a test knows who it is."""
    return survivors[0]


def bomba(names: list[str]) -> tuple[LobbyBook, str, list[str]]:
    book = LobbyBook()
    first, code = book.create(names[0])
    ids = [first] + [book.join(code, name)[0] for name in names[1:]]
    book.set_mode(first, "bomba")
    with mock.patch("server.lobby.secrets.choice", lowest_seat_first):
        book.start(first)
    wake(book, code)
    return book, code, ids


def run_out_the_clock(book: LobbyBook, code: str) -> None:
    lobby = book._lobbies[code]
    lobby.ends_at = time.time() - 1
    book.finish_if_due(code)


class BombaRuleTests(unittest.TestCase):
    def test_bomba_needs_two_players(self) -> None:
        book = LobbyBook()
        ada, _ = book.create("Ada")
        book.set_mode(ada, "bomba")
        with self.assertRaises(LobbyError):
            book.start(ada)

    def test_the_robot_hunts_the_lowest_pull(self) -> None:
        book, code, (ada, bea, cam) = bomba(["Ada", "Bea", "Cam"])
        self.assertTrue(players(book, code, ada)["Ada"]["chased"])
        book.record_shakes(ada, 5)
        book.record_shakes(cam, 5)
        self.assertTrue(players(book, code, ada)["Bea"]["chased"])
        book.record_shakes(bea, 10)
        chased = [name for name, row in players(book, code, ada).items() if row["chased"]]
        self.assertIn(chased, (["Ada"], ["Cam"]))

    def test_a_small_lead_does_not_move_the_target(self) -> None:
        book, code, (ada, bea) = bomba(["Ada", "Bea"])
        book.record_shakes(ada, 3)
        self.assertTrue(players(book, code, ada)["Bea"]["chased"])
        book.record_shakes(bea, 3)
        self.assertTrue(players(book, code, ada)["Bea"]["chased"])

    def test_arrival_knocks_out_that_player_and_the_rest_play_on(self) -> None:
        book, code, (ada, bea, cam) = bomba(["Ada", "Bea", "Cam"])
        book.finish_arrival(code, ada)
        snapshot = book.snapshot(code, bea)
        self.assertFalse(snapshot["finished"])
        self.assertTrue(snapshot["bomba"]["between"])
        self.assertEqual(snapshot["bomba"]["out"], ["Ada"])
        self.assertEqual(snapshot["bomba"]["out_reason"], "arrival")
        self.assertTrue(players(book, code, bea)["Ada"]["out"])
        self.assertFalse(book.scoring_open(code))
        self.assertEqual(book.record_shakes(bea, 3), (code, False))

    def test_the_closest_player_is_out_when_the_clock_runs_out(self) -> None:
        book, code, (ada, bea, cam) = bomba(["Ada", "Bea", "Cam"])
        book.remember_pose(code, 100.0, 0.0, 0.0, True)
        run_out_the_clock(book, code)
        snapshot = book.snapshot(code, bea)
        self.assertEqual(snapshot["bomba"]["out"], ["Ada"])
        self.assertEqual(snapshot["bomba"]["out_reason"], "clock")

    def test_a_tie_for_closest_knocks_out_everyone_tied(self) -> None:
        book, code, (ada, bea, cam, dee) = bomba(["Ada", "Bea", "Cam", "Dee"])
        # Halfway between Ada (0°) and Bea (90°).
        book.remember_pose(code, 60.0, 60.0, 45.0, True)
        run_out_the_clock(book, code)
        snapshot = book.snapshot(code, cam)
        self.assertEqual(sorted(snapshot["bomba"]["out"]), ["Ada", "Bea"])
        self.assertTrue(snapshot["bomba"]["between"])
        self.assertEqual(snapshot["bomba"]["alive"], 2)

    def test_a_tie_between_the_last_two_leaves_nobody(self) -> None:
        book, code, (ada, bea) = bomba(["Ada", "Bea"])
        run_out_the_clock(book, code)
        snapshot = book.snapshot(code, ada)
        self.assertTrue(snapshot["finished"])
        self.assertEqual(snapshot["reason"], "draw")
        self.assertEqual(snapshot["winners"], [])
        self.assertEqual(sorted(snapshot["bomba"]["out"]), ["Ada", "Bea"])

    def test_the_last_one_standing_wins(self) -> None:
        book, code, (ada, bea) = bomba(["Ada", "Bea"])
        book.finish_arrival(code, ada)
        snapshot = book.snapshot(code, bea)
        self.assertTrue(snapshot["finished"])
        self.assertEqual(snapshot["reason"], "survivor")
        self.assertEqual(snapshot["winners"], ["Bea"])

    def test_regroup_spaces_the_survivors_and_next_round_opens_a_countdown(self) -> None:
        book, code, (ada, bea, cam) = bomba(["Ada", "Bea", "Cam"])
        book.record_shakes(bea, 4)
        book.finish_arrival(code, ada)
        self.assertFalse(book.next_round(code))
        self.assertTrue(book.regroup(code))
        snapshot = book.snapshot(code, bea)
        self.assertEqual(snapshot["bomba"]["round"], 2)
        self.assertEqual([(mark["name"], mark["seat"], mark["angle"]) for mark in snapshot["marks"]], [("Bea", 0, 0), ("Cam", 1, 180)])
        rows = players(book, code, bea)
        self.assertEqual(rows["Bea"]["shakes"], 0)
        self.assertTrue(rows["Ada"]["out"])
        with mock.patch("server.lobby.secrets.choice", lowest_seat_first):
            self.assertTrue(book.next_round(code))
        snapshot = book.snapshot(code, bea)
        self.assertFalse(snapshot["bomba"]["between"])
        self.assertEqual(snapshot["bomba"]["out"], [])
        self.assertGreater(snapshot["opens_at"], time.time() * 1000)
        self.assertTrue(players(book, code, bea)["Bea"]["chased"])
        wake(book, code)
        self.assertEqual(book.record_shakes(bea, 3)[1], True)
        book.record_shakes(ada, 3)
        self.assertEqual(players(book, code, bea)["Ada"]["shakes"], 0)
        self.assertEqual(book.playing_marks(code), [(bea, 0, False), (cam, 180, True)])

    def test_leaving_down_to_one_survivor_ends_the_game(self) -> None:
        book, code, (ada, bea, cam) = bomba(["Ada", "Bea", "Cam"])
        book.finish_arrival(code, ada)
        book.leave(cam)
        snapshot = book.snapshot(code, bea)
        self.assertTrue(snapshot["finished"])
        self.assertEqual(snapshot["winners"], ["Bea"])
        self.assertFalse(book.between_rounds(code))

    def test_the_first_target_is_random_and_always_a_survivor(self) -> None:
        firsts = set()
        for _ in range(40):
            book = LobbyBook()
            ada, code = book.create("Ada")
            book.join(code, "Bea")
            book.join(code, "Cam")
            book.set_mode(ada, "bomba")
            book.start(ada)
            firsts.update(name for name, row in players(book, code, ada).items() if row["chased"])
        self.assertGreater(len(firsts), 1)

    def test_the_winner_is_still_named_after_leaving(self) -> None:
        book, code, (ada, bea, cam) = bomba(["Ada", "Bea", "Cam"])
        book.finish_arrival(code, ada)
        book.regroup(code)
        book.next_round(code)
        wake(book, code)
        book.finish_arrival(code, bea)
        book.leave(cam)
        book.leave(bea)
        snapshot = book.snapshot(code, ada)
        self.assertEqual(snapshot["winners"], ["Cam"])
        self.assertEqual(snapshot["bomba"]["out"], ["Bea"])
        self.assertEqual(book.rematch(ada) is not None, True)

    def test_a_rematch_brings_everyone_back(self) -> None:
        book, code, (ada, bea) = bomba(["Ada", "Bea"])
        book.finish_arrival(code, bea)
        new_code = book.rematch(ada)
        snapshot = book.snapshot(new_code, bea)
        self.assertEqual(snapshot["mode"], "bomba")
        self.assertEqual(snapshot["last_match"], {"winners": ["Ada"]})
        self.assertFalse(snapshot["started"])
        self.assertTrue(all(not row.get("out") for row in snapshot["marks"]))


class HomeTests(unittest.TestCase):
    def test_home_chunks_bring_the_robot_back_to_the_center(self) -> None:
        pose = Pose()
        pose.apply("SPIN", 2500, 1)
        pose.apply("DRIVE", 4000, -1)
        self.assertGreater(math.hypot(pose.x, pose.y), 100)
        for _ in range(200):
            chunk = home_chunk(pose)
            if chunk is None:
                break
            pose.apply(chunk.command, chunk.steps, chunk.direction)
        self.assertIsNone(home_chunk(pose))
        self.assertLessEqual(math.hypot(pose.x, pose.y), HOME_RADIUS_MM)

    def test_an_unknown_pose_does_not_drive_home(self) -> None:
        pose = Pose()
        pose.apply("DRIVE", 1000, -1)
        pose.mark_unknown()
        self.assertIsNone(home_chunk(pose))


def first_target_lowest_seat(book: LobbyBook, lobby) -> None:
    lobby.chase_id = None
    book._retarget(lobby)


class BombaGameTests(unittest.TestCase):
    def test_three_players_play_down_to_one_with_the_robot(self) -> None:
        asyncio.run(self._game())

    async def _game(self) -> None:
        app = create_app()
        real = app["bridge"]
        robot = FakeRobot()
        app["bridge"] = robot
        sockets = [FakeSocket(), FakeSocket(), FakeSocket()]
        game = None
        try:
            with (
                mock.patch("server.app.BOMBA_BREAK_SECONDS", 0.01),
                mock.patch("server.lobby.COUNTDOWN_SECONDS", 0),
                mock.patch("server.lobby.BOMBA_COUNTDOWN_SECONDS", 0),
                mock.patch("server.lobby.LobbyBook._first_target", first_target_lowest_seat),
            ):
                ada = await handle_text(app, sockets[0], None, json.dumps({"type": "create", "name": "Ada", "shaking": True}))
                code = sockets[0].sent[-1]["code"]
                for socket, name in zip(sockets[1:], ("Bea", "Cam")):
                    await handle_text(app, socket, None, json.dumps({"type": "join", "name": name, "code": code, "shaking": True}))
                await handle_text(app, sockets[0], ada, json.dumps({"type": "mode", "mode": "bomba"}))
                await handle_text(app, sockets[0], ada, json.dumps({"type": "start"}))
                game = app["bomba_tasks"][code]
                await asyncio.wait_for(game, 5)
            final = sockets[2].sent[-1]
            self.assertTrue(final["finished"])
            self.assertEqual(final["reason"], "survivor")
            self.assertEqual(final["winners"], ["Cam"])
            knockouts = [
                message["bomba"]["out"]
                for message in sockets[2].sent
                if message.get("type") == "lobby" and message["bomba"] and message["bomba"]["between"]
            ]
            self.assertEqual(knockouts[0], ["Ada"])
            self.assertEqual(final["bomba"]["out"], ["Bea"])
            self.assertTrue(any(message.get("bomba", {}) and message["bomba"]["homing"] for message in sockets[2].sent if message.get("type") == "lobby"))
            # Ada at 0°, then back home in reverse, then Bea at 0° again.
            self.assertIn(("DRIVE", robot.commands[-1][1], -1), robot.commands)
            self.assertTrue(any(direction == 1 for command, _, direction in robot.commands if command == "DRIVE"))
        finally:
            if game is not None and not game.done():
                game.cancel()
                await asyncio.gather(game, return_exceptions=True)
            real.close()


if __name__ == "__main__":
    unittest.main()
