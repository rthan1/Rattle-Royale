"""Every phone hears about a rematch."""

import asyncio
import json
import unittest

from server.app import create_app, handle_text
from server.lobby import MAX_PLAYERS, LobbyBook, LobbyError


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed = False

    async def send_str(self, data: str) -> None:
        self.sent.append(json.loads(data))


class RematchNoticeTests(unittest.TestCase):
    def test_every_player_is_told_the_new_code_and_who_started_it(self) -> None:
        asyncio.run(self._rematch())

    async def _rematch(self) -> None:
        app = create_app()
        book: LobbyBook = app["book"]
        sockets = [FakeSocket() for _ in range(MAX_PLAYERS)]
        try:
            creator = await handle_text(app, sockets[0], None, json.dumps({"type": "create", "name": "P0", "shaking": True}))
            old = sockets[0].sent[-1]["code"]
            ids = [creator]
            for number in range(1, MAX_PLAYERS):
                joined = {"type": "join", "name": f"P{number}", "code": old, "shaking": True}
                ids.append(await handle_text(app, sockets[number], None, json.dumps(joined)))
            book.start(creator)
            book._lobbies[old].ends_at = 0
            self.assertTrue(book.finish_if_due(old))
            finished = [book.snapshot(old, player_id) for player_id in ids]
            self.assertTrue(all(snapshot["finished"] for snapshot in finished))
            self.assertEqual([snapshot["creator"] for snapshot in finished], [True] + [False] * (MAX_PLAYERS - 1))
            for socket in sockets:
                socket.sent.clear()

            await handle_text(app, sockets[1], ids[1], json.dumps({"type": "rematch"}))
            self.assertEqual(sockets[1].sent[-1]["type"], "error")
            self.assertTrue(all(socket.sent == [] for index, socket in enumerate(sockets) if index != 1))

            await handle_text(app, sockets[0], creator, json.dumps({"type": "rematch"}))
            codes = set()
            self.assertEqual([socket.sent[-1]["creator"] for socket in sockets], [True] + [False] * (MAX_PLAYERS - 1))
            for socket in sockets:
                notice, snapshot = socket.sent[-2], socket.sent[-1]
                self.assertEqual(notice["type"], "rematched")
                self.assertEqual(notice["by"], "P0")
                self.assertNotEqual(notice["code"], old)
                self.assertEqual(snapshot["type"], "lobby")
                self.assertEqual(snapshot["code"], notice["code"])
                self.assertEqual(len(snapshot["players"]), MAX_PLAYERS)
                self.assertFalse(snapshot["started"])
                codes.add(notice["code"])
            self.assertEqual(len(codes), 1)
        finally:
            app["bridge"].close()

    def test_lobby_messages_say_whether_the_robot_is_online_and_where_to_invite(self) -> None:
        asyncio.run(self._lobby_extras())

    async def _lobby_extras(self) -> None:
        app = create_app("https://party.example.test/")
        socket = FakeSocket()
        try:
            await handle_text(app, socket, None, json.dumps({"type": "create", "name": "Ada", "shaking": True}))
            lobby = socket.sent[-1]
            self.assertEqual(lobby["type"], "lobby")
            self.assertIs(lobby["robot_online"], False)
            self.assertEqual(lobby["public_url"], "https://party.example.test")
        finally:
            app["bridge"].close()
        plain = create_app()
        try:
            await handle_text(plain, socket, None, json.dumps({"type": "create", "name": "Bea", "shaking": True}))
            self.assertIsNone(socket.sent[-1]["public_url"])
        finally:
            plain["bridge"].close()

    def test_creator_name_follows_the_creator(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        book.join(code, "Bea")
        self.assertEqual(book.creator_name(code), "Ada")
        book.leave(ada)
        self.assertEqual(book.creator_name(code), "Bea")
        self.assertIsNone(book.creator_name("NONE"))
        with self.assertRaises(LobbyError):
            book.rematch(ada)


if __name__ == "__main__":
    unittest.main()
