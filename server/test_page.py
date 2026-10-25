"""The page and the robot picture it draws on the arena."""

import asyncio
import unittest

from aiohttp.test_utils import TestClient, TestServer

from server.app import create_app

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PageTests(unittest.TestCase):
    def test_the_page_loads_the_robot_picture_the_server_serves(self) -> None:
        asyncio.run(self._fetch())

    async def _fetch(self) -> None:
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            page = await client.get("/")
            self.assertEqual(page.status, 200)
            self.assertIn('robotImage.src = "/robot.png"', await page.text())
            image = await client.get("/robot.png")
            self.assertEqual(image.status, 200)
            self.assertEqual(image.headers["Content-Type"], "image/png")
            self.assertTrue((await image.read()).startswith(PNG_SIGNATURE))
        app["bridge"].close()


if __name__ == "__main__":
    unittest.main()
