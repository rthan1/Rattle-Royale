"""Fading pull and the chase target."""

import time
import unittest

from server.lobby import (
    COUNTDOWN_SECONDS,
    PULL_HALF_LIFE_SECONDS,
    ROUND_SECONDS,
    SCORE_GRACE_SECONDS,
    LobbyBook,
)


def wake(book: LobbyBook, code: str) -> None:
    lobby = book._lobbies[code]
    now = time.time()
    lobby.opens_at = now - 1
    lobby.pull_at = now


def players(book: LobbyBook, code: str, viewer_id: str) -> dict[str, dict]:
    snapshot = book.snapshot(code, viewer_id)
    return {player["name"]: player for player in snapshot["players"]}


class PullTests(unittest.TestCase):
    def test_an_accepted_shake_adds_one_pull_and_claims_the_target(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        book.record_shakes(ada, 5)
        book.start(ada)
        wake(book, code)
        book.record_shakes(ada, 5)
        ada_row = players(book, code, ada)["Ada"]
        self.assertEqual(ada_row["shakes"], 5)
        self.assertEqual(ada_row["pull"], 5)
        self.assertTrue(ada_row["chased"])

    def test_a_jump_over_the_limit_does_not_add_pull(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        book.start(ada)
        wake(book, code)
        book.record_shakes(ada, 13)
        ada_row = players(book, code, ada)["Ada"]
        self.assertEqual(ada_row["shakes"], 0)
        self.assertEqual(ada_row["pull"], 0)
        self.assertFalse(ada_row["chased"])
        book.record_shakes(ada, 12)
        ada_row = players(book, code, ada)["Ada"]
        self.assertEqual(ada_row["pull"], 12)
        self.assertTrue(ada_row["chased"])

    def test_half_life_cuts_pull_in_half_and_a_long_fade_clears_the_target(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        book.start(ada)
        wake(book, code)
        book.record_shakes(ada, 1)
        lobby = book._lobbies[code]
        book.decay_pull(code, now=lobby.pull_at + PULL_HALF_LIFE_SECONDS)
        self.assertEqual(players(book, code, ada)["Ada"]["pull"], 0.5)
        self.assertTrue(players(book, code, ada)["Ada"]["chased"])
        book.decay_pull(code, now=lobby.pull_at + 30)
        ada_row = players(book, code, ada)["Ada"]
        self.assertEqual(ada_row["pull"], 0)
        self.assertFalse(ada_row["chased"])

    def test_a_small_lead_keeps_the_target_and_a_clear_lead_switches_it(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        bea, _ = book.join(code, "Bea")
        book.start(ada)
        wake(book, code)
        book.record_shakes(ada, 10)
        book.record_shakes(bea, 11)
        rows = players(book, code, ada)
        self.assertTrue(rows["Ada"]["chased"])
        self.assertFalse(rows["Bea"]["chased"])
        book.record_shakes(bea, 12)
        rows = players(book, code, ada)
        self.assertFalse(rows["Ada"]["chased"])
        self.assertTrue(rows["Bea"]["chased"])
        self.assertEqual([player["name"] for player in book.snapshot(code, ada)["players"]], ["Bea", "Ada"])

    def test_a_tie_keeps_the_current_target(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        bea, _ = book.join(code, "Bea")
        book.start(ada)
        wake(book, code)
        book.record_shakes(bea, 8)
        book.record_shakes(ada, 8)
        rows = players(book, code, ada)
        self.assertTrue(rows["Bea"]["chased"])
        self.assertFalse(rows["Ada"]["chased"])

    def test_the_next_player_is_chased_when_the_target_leaves(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        bea, _ = book.join(code, "Bea")
        book.start(ada)
        wake(book, code)
        book.record_shakes(ada, 10)
        book.record_shakes(bea, 4)
        book.leave(ada)
        bea_row = players(book, code, bea)["Bea"]
        self.assertEqual(bea_row["seat"], 1)
        self.assertTrue(bea_row["chased"])

    def test_pull_freezes_when_the_clock_names_the_chased_player(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        bea, _ = book.join(code, "Bea")
        book.start(ada)
        wake(book, code)
        book.record_shakes(ada, 8)
        book.record_shakes(bea, 2)
        lobby = book._lobbies[code]
        lobby.players[0].pull = 8
        lobby.players[1].pull = 2
        lobby.players[1].shakes = 30
        lobby.ends_at = time.time() - 10
        lobby.pull_at = lobby.ends_at + SCORE_GRACE_SECONDS - PULL_HALF_LIFE_SECONDS
        self.assertTrue(book.finish_if_due(code))
        snapshot = book.snapshot(code, ada)
        self.assertEqual(snapshot["reason"], "clock")
        self.assertEqual(snapshot["winners"], ["Ada"])
        self.assertEqual(players(book, code, ada)["Ada"]["pull"], 4)
        self.assertFalse(book.decay_pull(code, now=time.time() + 50))
        self.assertEqual(players(book, code, ada)["Ada"]["pull"], 4)
        self.assertFalse(book.pull_round_open(code))

    def test_a_quiet_clock_is_a_draw(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        book.start(ada)
        wake(book, code)
        lobby = book._lobbies[code]
        lobby.ends_at = time.time() - 10
        self.assertTrue(book.finish_if_due(code))
        snapshot = book.snapshot(code, ada)
        self.assertEqual(snapshot["reason"], "draw")
        self.assertEqual(snapshot["winners"], [])

    def test_a_chunk_in_flight_holds_the_clock(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        book.start(ada)
        wake(book, code)
        book.record_shakes(ada, 4)
        lobby = book._lobbies[code]
        lobby.ends_at = time.time() - 10
        book.set_motion(code, True)
        self.assertFalse(book.finish_if_due(code))
        self.assertFalse(book.snapshot(code, ada)["finished"])
        book.set_motion(code, False)
        self.assertTrue(book.finish_if_due(code))
        self.assertEqual(book.snapshot(code, ada)["winners"], ["Ada"])

    def test_shakes_during_the_countdown_do_not_score(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        started = time.time()
        book.start(ada)
        lobby = book._lobbies[code]
        self.assertGreaterEqual(lobby.opens_at - started, COUNTDOWN_SECONDS - 0.05)
        self.assertAlmostEqual(lobby.ends_at - lobby.opens_at, ROUND_SECONDS)
        book.record_shakes(ada, 6)
        self.assertEqual(players(book, code, ada)["Ada"]["shakes"], 0)
        self.assertFalse(players(book, code, ada)["Ada"]["chased"])
        self.assertEqual(book.snapshot(code, ada)["pose"], {"x": 0.0, "y": 0.0, "heading": 0.0, "known": True})
        wake(book, code)
        book.record_shakes(ada, 6)
        self.assertEqual(players(book, code, ada)["Ada"]["shakes"], 6)
        self.assertTrue(players(book, code, ada)["Ada"]["chased"])


if __name__ == "__main__":
    unittest.main()
