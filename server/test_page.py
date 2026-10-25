"""The page and the robot picture it draws on the arena."""

import asyncio
import unittest

from aiohttp.test_utils import TestClient, TestServer

from server.app import create_app


class PageTests(unittest.TestCase):
    def test_the_page_loads_the_robot_picture_the_server_serves(self) -> None:
        asyncio.run(self._fetch())

    async def _fetch(self) -> None:
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            page = await client.get("/")
            self.assertEqual(page.status, 200)
            self.assertIn('robotImage.src = "/robot.svg"', await page.text())
            image = await client.get("/robot.svg")
            self.assertEqual(image.status, 200)
            self.assertEqual(image.headers["Content-Type"], "image/svg+xml")
            self.assertTrue((await image.read()).startswith(b"<svg"))
        app["bridge"].close()

    def test_the_invite_qr_code_is_an_svg_for_a_link(self) -> None:
        asyncio.run(self._qr())

    async def _qr(self) -> None:
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            good = await client.get("/qr.svg", params={"data": "https://example.test/?code=ABCD"})
            self.assertEqual(good.status, 200)
            self.assertEqual(good.headers["Content-Type"], "image/svg+xml")
            self.assertIn(b"<svg", await good.read())
            not_a_link = await client.get("/qr.svg", params={"data": "javascript:alert(1)"})
            self.assertEqual(not_a_link.status, 400)
            too_long = await client.get("/qr.svg", params={"data": "https://example.test/" + "a" * 300})
            self.assertEqual(too_long.status, 400)
        app["bridge"].close()


if __name__ == "__main__":
    unittest.main()
