"""Seat assignment for a lobby."""

import unittest

from server.lobby import MAX_PLAYERS, LobbyBook, LobbyError
from server.test_pull import wake


def seats(book: LobbyBook, code: str, viewer_id: str) -> dict[str, dict]:
    snapshot = book.snapshot(code, viewer_id)
    return {player["name"]: player for player in snapshot["players"]}


class SeatTests(unittest.TestCase):
    def test_creator_is_seat_zero_and_the_next_player_is_seat_one(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        book.join(code, "Bea")
        players = seats(book, code, ada)
        self.assertEqual(players["Ada"]["seat"], 0)
        self.assertEqual(players["Bea"]["seat"], 1)
        self.assertNotIn("angle", players["Ada"])
        snapshot = book.snapshot(code, ada)
        self.assertEqual(snapshot["pose"], {"x": 0.0, "y": 0.0, "heading": 0.0, "known": True})
        self.assertEqual([mark["angle"] for mark in snapshot["marks"]], [0, 180])

    def test_leave_before_start_packs_later_seats(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        bea, _ = book.join(code, "Bea")
        book.join(code, "Cam")
        before = book.snapshot(code, ada)
        self.assertEqual([mark["angle"] for mark in before["marks"]], [0, 120, 240])
        book.leave(bea)
        players = seats(book, code, ada)
        self.assertEqual(list(players), ["Ada", "Cam"])
        self.assertEqual(players["Ada"]["seat"], 0)
        self.assertEqual(players["Cam"]["seat"], 1)
        after = book.snapshot(code, ada)
        self.assertEqual([mark["angle"] for mark in after["marks"]], [0, 180])
        self.assertEqual(after["pose"], {"x": 0.0, "y": 0.0, "heading": 0.0, "known": True})

    def test_start_stores_angles_and_a_later_leave_keeps_them(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        bea, _ = book.join(code, "Bea")
        book.start(ada)
        players = seats(book, code, bea)
        self.assertEqual(players["Ada"]["angle"], 0)
        self.assertEqual(players["Bea"]["angle"], 180)
        book.leave(ada)
        players = seats(book, code, bea)
        self.assertEqual(list(players), ["Bea"])
        self.assertEqual(players["Bea"]["seat"], 1)
        self.assertEqual(players["Bea"]["angle"], 180)

    def test_eighth_player_is_accepted_and_ninth_is_refused(self) -> None:
        book = LobbyBook()
        creator, code = book.create("P0")
        for number in range(1, MAX_PLAYERS):
            book.join(code, f"P{number}")
        players = seats(book, code, creator)
        self.assertEqual(len(players), MAX_PLAYERS)
        self.assertEqual(players["P7"]["seat"], 7)
        with self.assertRaises(LobbyError) as caught:
            book.join(code, "P8")
        self.assertEqual(caught.exception.message, "This lobby is full.")

    def test_a_second_lobby_is_refused_while_one_is_open(self) -> None:
        book = LobbyBook()
        _, code = book.create("Ada")
        with self.assertRaises(LobbyError) as caught:
            book.create("Bea")
        self.assertEqual(caught.exception.message, f"A lobby is already open. Join {code}.")
        book.start(book.member_ids(code)[0])
        with self.assertRaises(LobbyError) as caught:
            book.create("Bea")
        self.assertEqual(caught.exception.message, "A game is already running.")

    def test_a_lobby_can_be_created_again_after_the_last_player_leaves(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        book.leave(ada)
        _, new_code = book.create("Bea")
        self.assertNotEqual(new_code, code)
        self.assertEqual(len(book.snapshot(new_code, book.member_ids(new_code)[0])["players"]), 1)


class RematchTests(unittest.TestCase):
    def finished_lobby(self) -> tuple[LobbyBook, str, str, str]:
        book = LobbyBook()
        ada, code = book.create("Ada")
        bea, _ = book.join(code, "Bea")
        book.start(ada)
        book.record_shakes(bea, 4)
        book._lobbies[code].ends_at = 0
        self.assertTrue(book.finish_if_due(code))
        return book, ada, bea, code

    def test_rematch_moves_everyone_to_a_fresh_lobby_with_a_new_code(self) -> None:
        book, ada, bea, old = self.finished_lobby()
        code = book.rematch(ada)
        self.assertNotEqual(code, old)
        self.assertEqual(book.member_ids(old), [])
        snapshot = book.snapshot(code, ada)
        self.assertFalse(snapshot["started"])
        self.assertFalse(snapshot["finished"])
        self.assertEqual(snapshot["winners"], [])
        self.assertTrue(snapshot["creator"])
        players = seats(book, code, bea)
        self.assertEqual(players["Bea"]["shakes"], 0)
        self.assertNotIn("angle", players["Bea"])
        self.assertEqual(book.member_ids(code), [ada, bea])

    def test_new_players_can_join_the_rematch_and_old_ones_can_leave(self) -> None:
        book, ada, bea, _ = self.finished_lobby()
        code = book.rematch(ada)
        book.leave(ada)
        book.join(code, "Cam")
        players = seats(book, code, bea)
        self.assertEqual(list(players), ["Bea", "Cam"])
        self.assertEqual(players["Cam"]["seat"], 1)
        self.assertTrue(book.snapshot(code, bea)["creator"])

    def test_scores_restart_from_zero_in_the_rematch(self) -> None:
        book, ada, bea, _ = self.finished_lobby()
        code = book.rematch(ada)
        book.start(ada)
        wake(book, code)
        book.record_shakes(bea, 3)
        self.assertEqual(seats(book, code, bea)["Bea"]["shakes"], 3)

    def test_only_the_creator_can_rematch_and_only_after_the_game(self) -> None:
        book, ada, bea, _ = self.finished_lobby()
        with self.assertRaises(LobbyError) as caught:
            book.rematch(bea)
        self.assertEqual(caught.exception.message, "Only the creator can start a rematch.")
        book.rematch(ada)
        with self.assertRaises(LobbyError) as caught:
            book.rematch(ada)
        self.assertEqual(caught.exception.message, "The game is not over yet.")

    def test_a_new_lobby_draws_the_robot_in_the_middle(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        snapshot = book.snapshot(code, ada)
        self.assertEqual(snapshot["marks"], [{"seat": 0, "angle": 0, "you": True, "chased": False}])
        self.assertEqual(snapshot["pose"], {"x": 0.0, "y": 0.0, "heading": 0.0, "known": True})

    def test_rematch_keeps_the_result_map_until_the_next_start(self) -> None:
        book, ada, bea, old = self.finished_lobby()
        finished = book._lobbies[old]
        finished.pose_x = 40
        finished.pose_y = -15
        finished.pose_heading = 90
        finished.pose_known = False
        finished.chase_id = bea
        code = book.rematch(ada)
        snapshot = book.snapshot(code, ada)
        self.assertEqual(snapshot["pose"], {"x": 40, "y": -15, "heading": 90, "known": False})
        self.assertEqual(snapshot["marks"][0]["angle"], 0)
        self.assertTrue(snapshot["marks"][0]["you"])
        self.assertFalse(snapshot["marks"][0]["chased"])
        self.assertEqual(snapshot["marks"][1]["angle"], 180)
        self.assertTrue(snapshot["marks"][1]["chased"])
        book.join(code, "Cam")
        held = book.snapshot(code, ada)
        self.assertEqual([mark["seat"] for mark in held["marks"]], [0, 1])
        self.assertEqual(held["pose"]["x"], 40)
        book.start(ada)
        started = book.snapshot(code, ada)
        self.assertEqual(started["pose"], {"x": 0.0, "y": 0.0, "heading": 0.0, "known": True})
        self.assertEqual([mark["angle"] for mark in started["marks"]], [0, 120, 240])
        self.assertTrue(all(mark["chased"] is False for mark in started["marks"]))


if __name__ == "__main__":
    unittest.main()
