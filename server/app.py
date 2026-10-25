"""Phone connection, lobbies, and a 45-second chase.

A phone can create or join a lobby of up to eight players. Each player gets a
seat and a floor mark. The creator starts the game. A 3-second countdown runs
before shakes count, so the host cannot start early. The page draws the arena
and the robot pose from the server. Shakes then add pull, and the robot creeps
toward the leader when the Arduino is online. Reaching a mark wins. If time
runs out, the chased player wins.
"""

import asyncio
import json
import logging
import time

from aiohttp import ClientConnectionError, WSMsgType, web

from server.bridge import Bridge
from server.chase import follow
from server.lobby import PULL_TICK_SECONDS, LobbyBook, LobbyError

HOST = "0.0.0.0"
PORT = 8080

log = logging.getLogger(__name__)

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Rattle Royale</title>
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      min-height: 100dvh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #111;
      color: #f4f4f4;
      font-family: sans-serif;
    }
    main { width: min(24rem, 100%); padding: 1.5rem; box-sizing: border-box; }
    #status { font-size: 1.1rem; margin: 0 0 1.25rem; color: #aaa; text-align: center; }
    label { display: block; color: #ccc; }
    input, button { font: inherit; font-size: 1.1rem; }
    input {
      width: 100%;
      box-sizing: border-box;
      margin: 0.35rem 0 0.9rem;
      padding: 0.75rem;
    }
    button {
      width: 100%;
      margin: 0 0 0.9rem;
      padding: 0.85rem;
      touch-action: manipulation;
    }
    #clock { font-size: 2.5rem; margin: 0 0 0.5rem; }
    #result { font-size: 2rem; margin: 0 0 1rem; }
    #error { min-height: 1.2rem; margin: 0; color: #ffb4b4; text-align: center; }
    #waiting { margin: 0 0 0.9rem; color: #aaa; }
    #lobby { text-align: center; }
    #lobby-code {
      font-size: 3rem;
      letter-spacing: 0.18rem;
      margin: 0 0 0.25rem;
    }
    #lobby-count { margin: 0 0 1rem; color: #aaa; }
    #notice { font-size: 1.15rem; margin: 0 0 1rem; color: #b4e0ff; }
    #your-seat { font-size: 2rem; margin: 0 0 0.25rem; }
    #your-mark { margin: 0 0 0.35rem; color: #aaa; }
    #chase { font-size: 1.25rem; margin: 0 0 0.75rem; }
    #arena {
      width: 100%;
      height: auto;
      display: block;
      margin: 0 0 1rem;
      background: #1c1c1c;
      border-radius: 0.5rem;
    }
    #players { list-style: none; padding: 0; margin: 0 0 1.25rem; font-size: 1.35rem; }
    #players li { padding: 0.35rem 0; }
    #shakes { font-size: 1.6rem; margin: 0 0 0.4rem; text-align: center; }
    #shake-note { margin: 0 0 0.9rem; color: #aaa; font-size: 0.95rem; text-align: center; }
  </style>
</head>
<body>
  <main>
    <p id="status">Connecting</p>
    <p id="shakes" hidden>Shakes: 0</p>
    <button id="enable-shake" type="button">Enable shaking</button>
    <p id="shake-note">Enable shaking to create or join a lobby.</p>
    <section id="join" hidden>
      <label for="name">Name</label>
      <input id="name" maxlength="20" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" enterkeyhint="done">
      <button id="create" type="button">Create lobby</button>
      <label for="code">Lobby code</label>
      <input id="code" maxlength="4" autocomplete="off" autocorrect="off" autocapitalize="characters" spellcheck="false" enterkeyhint="go">
      <button id="join-lobby" type="button">Join lobby</button>
    </section>
    <section id="lobby" hidden>
      <p id="notice" hidden></p>
      <p id="lobby-code"></p>
      <p id="lobby-count"></p>
      <p id="your-seat"></p>
      <p id="your-mark"></p>
      <p id="chase" hidden></p>
      <canvas id="arena" width="320" height="320" hidden></canvas>
      <ul id="players"></ul>
      <p id="clock" hidden></p>
      <p id="result" hidden></p>
      <button id="start" type="button" hidden>Start game</button>
      <button id="rematch" type="button" hidden>Rematch</button>
      <p id="waiting" hidden>Waiting for the creator to start</p>
      <button id="leave" type="button">Leave lobby</button>
    </section>
    <p id="error"></p>
  </main>
  <script>
    const statusEl = document.getElementById("status");
    const joinEl = document.getElementById("join");
    const lobbyEl = document.getElementById("lobby");
    const errorEl = document.getElementById("error");
    const nameEl = document.getElementById("name");
    const codeEl = document.getElementById("code");

    let socket = null;
    let inLobby = false;
    let playing = false;
    let retryTimer = null;
    let roundOpensAt = null;
    let roundEndsAt = null;
    let countdownTimer = null;
    let lobbyMessage = null;

    function stopCountdown() {
      if (countdownTimer !== null) {
        clearInterval(countdownTimer);
        countdownTimer = null;
      }
    }

    function showNotice(text) {
      const notice = document.getElementById("notice");
      notice.textContent = text;
      notice.hidden = !text;
    }

    function rematchText(message) {
      const who = message.by ? message.by + " started a rematch." : "Rematch!";
      return who + " New lobby code: " + message.code;
    }

    function showJoin() {
      showNotice("");
      stopCountdown();
      showingReady = false;
      playing = false;
      roundOpensAt = null;
      roundEndsAt = null;
      lobbyMessage = null;
      resetShakes();
      shakesEl.hidden = true;
      lobbyEl.hidden = true;
      joinEl.hidden = !shaking;
    }

    function winnerText(message) {
      const winners = message.winners || [];
      if (message.reason === "draw" || winners.length === 0) {
        return "Draw";
      }
      let text = winners.length === 1 ? winners[0] + " wins" : "Tie: " + winners.join(", ");
      if (message.reason === "arrival") {
        text += " — the robot got there";
      } else if (message.reason === "clock") {
        text += " — time ran out";
      }
      return text;
    }

    let showingReady = false;

    function runCountdown() {
      stopCountdown();
      const clock = document.getElementById("clock");
      function tick() {
        const now = Date.now();
        const ready = roundOpensAt !== null && now < roundOpensAt;
        if (ready) {
          showingReady = true;
          clock.textContent = String(Math.max(1, Math.ceil((roundOpensAt - now) / 1000)));
          return;
        }
        if (showingReady && lobbyMessage) {
          showingReady = false;
          showLobby(lobbyMessage);
          return;
        }
        const left = roundEndsAt === null ? 0 : Math.max(0, Math.ceil((roundEndsAt - now) / 1000));
        clock.textContent = left + "s";
        if (left <= 0) {
          stopCountdown();
        }
      }
      tick();
      countdownTimer = setInterval(tick, 200);
    }

    function drawArena(message) {
      const canvas = document.getElementById("arena");
      if (!message.started || !message.pose) {
        canvas.hidden = true;
        return;
      }
      canvas.hidden = false;
      const ctx = canvas.getContext("2d");
      const size = canvas.width;
      ctx.clearRect(0, 0, size, size);
      const radius = message.mark_radius || 152.4;
      const pad = 36;
      const half = size / 2 - pad;
      const scale = half / radius;
      const cx = size / 2;
      const cy = size / 2;
      function point(x, y) {
        return [cx + x * scale, cy - y * scale];
      }
      ctx.strokeStyle = "#3a3a3a";
      ctx.lineWidth = 2;
      ctx.strokeRect(cx - half, cy - half, half * 2, half * 2);
      ctx.beginPath();
      ctx.arc(cx, cy, half, 0, Math.PI * 2);
      ctx.strokeStyle = "#2a2a2a";
      ctx.stroke();
      message.players.forEach((player) => {
        if (player.angle == null) {
          return;
        }
        const radians = player.angle * Math.PI / 180;
        const spot = point(radius * Math.cos(radians), radius * Math.sin(radians));
        ctx.beginPath();
        ctx.arc(spot[0], spot[1], 12, 0, Math.PI * 2);
        ctx.fillStyle = player.chased ? "#e24b4b" : "#dedede";
        ctx.fill();
        if (player.you) {
          ctx.lineWidth = 3;
          ctx.strokeStyle = "#8ec8ff";
          ctx.stroke();
        }
        ctx.fillStyle = "#111";
        ctx.font = "bold 12px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(String(player.seat), spot[0], spot[1]);
      });
      const pose = message.pose;
      const robot = point(pose.x, pose.y);
      ctx.save();
      ctx.translate(robot[0], robot[1]);
      ctx.rotate(-pose.heading * Math.PI / 180);
      ctx.beginPath();
      ctx.moveTo(14, 0);
      ctx.lineTo(-9, 7);
      ctx.lineTo(-9, -7);
      ctx.closePath();
      ctx.fillStyle = pose.known ? "#ffc14d" : "#666";
      ctx.fill();
      ctx.restore();
    }

    function showLobby(message) {
      inLobby = true;
      lobbyMessage = message;
      const nowPlaying = message.started && !message.finished;
      if (nowPlaying && !playing) {
        resetShakes();
        showNotice("");
      }
      const previousEnd = roundEndsAt;
      const previousOpen = roundOpensAt;
      playing = nowPlaying;
      roundOpensAt = message.started ? message.opens_at : null;
      roundEndsAt = message.started ? message.ends_at : null;
      const ready = roundOpensAt !== null && Date.now() < roundOpensAt;
      shakesEl.hidden = !message.started || ready;
      errorEl.textContent = "";
      joinEl.hidden = true;
      lobbyEl.hidden = false;
      document.getElementById("lobby-code").textContent = message.code;
      document.getElementById("lobby-count").textContent =
        message.players.length + " of " + message.max;
      document.getElementById("start").hidden = !(message.creator && !message.started);
      document.getElementById("rematch").hidden = !(message.creator && message.finished);
      const waiting = document.getElementById("waiting");
      waiting.hidden = message.creator || (message.started && !message.finished);
      waiting.textContent = message.finished
        ? "Waiting for the creator to start a rematch"
        : "Waiting for the creator to start";
      document.getElementById("leave").hidden = playing;
      const mine = message.players.find((player) => player.you);
      document.getElementById("your-seat").textContent = mine ? "You are seat " + mine.seat : "";
      document.getElementById("your-mark").textContent = mine ? "Stand on mark " + mine.seat : "";
      const chase = document.getElementById("chase");
      if (ready) {
        chase.hidden = false;
        chase.textContent = "Get ready";
      } else if (message.started) {
        const chased = message.players.find((player) => player.chased);
        chase.hidden = false;
        if (!chased) {
          chase.textContent = "The robot is holding still";
        } else if (chased.you) {
          chase.textContent = "The robot is coming for you";
        } else {
          chase.textContent = "The robot is chasing " + chased.name;
        }
      } else {
        chase.hidden = true;
        chase.textContent = "";
      }
      const clock = document.getElementById("clock");
      const result = document.getElementById("result");
      if (playing) {
        clock.hidden = false;
        result.hidden = true;
        result.textContent = "";
        if (countdownTimer === null || previousOpen !== roundOpensAt || previousEnd !== roundEndsAt) {
          runCountdown();
        }
      } else if (message.finished) {
        if (mine) {
          shakeCount = mine.shakes;
          showShakeCount();
        }
        stopCountdown();
        clock.hidden = true;
        result.hidden = false;
        result.textContent = winnerText(message);
      } else {
        stopCountdown();
        clock.hidden = true;
        result.hidden = true;
        result.textContent = "";
      }
      const list = document.getElementById("players");
      list.replaceChildren();
      message.players.forEach((player) => {
        const item = document.createElement("li");
        const marker = player.you ? " (you)" : "";
        let text = player.name + " — seat " + player.seat + marker;
        if (message.started) {
          text += " — " + player.shakes + " — pull " + Number(player.pull).toFixed(2);
          if (player.chased) {
            text += " — chased";
          }
        }
        item.textContent = text;
        list.append(item);
      });
      drawArena(message);
    }

    function send(message) {
      if ((message.type === "create" || message.type === "join") && !shaking) {
        errorEl.textContent = "Enable shaking before joining a lobby.";
        return;
      }
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        errorEl.textContent = "Still connecting.";
        return;
      }
      errorEl.textContent = "";
      socket.send(JSON.stringify(message));
    }

    document.getElementById("create").addEventListener("click", () => {
      send({ type: "create", name: nameEl.value, shaking: true });
    });
    document.getElementById("join-lobby").addEventListener("click", () => {
      send({ type: "join", name: nameEl.value, code: codeEl.value, shaking: true });
    });
    document.getElementById("start").addEventListener("click", () => {
      send({ type: "start" });
    });
    document.getElementById("rematch").addEventListener("click", () => {
      send({ type: "rematch" });
    });
    document.getElementById("leave").addEventListener("click", () => {
      send({ type: "leave" });
    });

    const SHAKE_THRESHOLD = 15;
    const SHAKE_GAP_MS = 150;
    const shakesEl = document.getElementById("shakes");
    const enableShakeEl = document.getElementById("enable-shake");
    const shakeNoteEl = document.getElementById("shake-note");
    let shakeCount = 0;
    let shaking = false;
    let lastShakeAt = 0;

    function resetShakes() {
      shakeCount = 0;
      lastShakeAt = 0;
      showShakeCount();
    }

    function showShakeCount() {
      shakesEl.textContent = "Shakes: " + shakeCount;
    }

    function dismissKeyboard() {
      nameEl.blur();
      codeEl.blur();
      const active = document.activeElement;
      if (active && active !== document.body && active.blur) {
        active.blur();
      }
    }

    function replaceRange(input, text) {
      const start = input.selectionStart == null ? input.value.length : input.selectionStart;
      const end = input.selectionEnd == null ? input.value.length : input.selectionEnd;
      const next = (input.value.slice(0, start) + text + input.value.slice(end)).slice(0, input.maxLength || undefined);
      input.value = next;
      const caret = Math.min(start + text.length, input.value.length);
      input.setSelectionRange(caret, caret);
    }

    function deleteRange(input, backward) {
      const start = input.selectionStart == null ? input.value.length : input.selectionStart;
      const end = input.selectionEnd == null ? input.value.length : input.selectionEnd;
      if (start !== end) {
        input.value = input.value.slice(0, start) + input.value.slice(end);
        input.setSelectionRange(start, start);
        return;
      }
      if (backward && start > 0) {
        input.value = input.value.slice(0, start - 1) + input.value.slice(end);
        input.setSelectionRange(start - 1, start - 1);
      } else if (!backward && end < input.value.length) {
        input.value = input.value.slice(0, start) + input.value.slice(end + 1);
        input.setSelectionRange(start, start);
      }
    }

    function watchTyping(input) {
      let handledByKey = false;
      input.addEventListener("pointerdown", () => {
        input.readOnly = false;
      });
      input.addEventListener("keydown", (event) => {
        if (event.metaKey || event.ctrlKey || event.altKey) {
          return;
        }
        if (event.key === "Enter") {
          event.preventDefault();
          return;
        }
        if (event.key === "Backspace" || event.key === "Delete") {
          event.preventDefault();
          handledByKey = true;
          deleteRange(input, event.key === "Backspace");
          return;
        }
        if (event.key.length === 1) {
          event.preventDefault();
          handledByKey = true;
          replaceRange(input, event.key);
        }
      });
      input.addEventListener("beforeinput", (event) => {
        if (event.inputType === "historyUndo" || event.inputType === "historyRedo" || event.inputType === "insertLineBreak") {
          event.preventDefault();
          handledByKey = false;
          return;
        }
        if (handledByKey) {
          event.preventDefault();
          handledByKey = false;
          return;
        }
        if (event.inputType === "insertText" || event.inputType === "insertFromPaste") {
          event.preventDefault();
          if (event.data) {
            replaceRange(input, event.data);
          }
          return;
        }
        if (event.inputType === "deleteContentBackward" || event.inputType === "deleteContentForward") {
          event.preventDefault();
          deleteRange(input, event.inputType === "deleteContentBackward");
        }
      });
    }

    watchTyping(nameEl);
    watchTyping(codeEl);

    function onMotion(event) {
      if (!shaking || !playing || document.visibilityState === "hidden") {
        return;
      }
      if (roundOpensAt !== null && Date.now() < roundOpensAt) {
        return;
      }
      if (roundEndsAt !== null && Date.now() >= roundEndsAt) {
        return;
      }
      const reading = event.accelerationIncludingGravity;
      if (!reading || reading.x == null || reading.y == null || reading.z == null) {
        shakeNoteEl.textContent = "This phone cannot shake.";
        return;
      }
      const strength = Math.hypot(reading.x, reading.y, reading.z);
      if (strength < SHAKE_THRESHOLD) {
        return;
      }
      nameEl.readOnly = true;
      codeEl.readOnly = true;
      dismissKeyboard();
      const now = performance.now();
      if (now - lastShakeAt < SHAKE_GAP_MS) {
        return;
      }
      lastShakeAt = now;
      shakeCount += 1;
      showShakeCount();
      send({ type: "shakes", total: shakeCount });
    }

    async function enableShaking() {
      const motion = window.DeviceMotionEvent;
      if (!motion) {
        enableShakeEl.hidden = true;
        shakeNoteEl.textContent = "This phone cannot shake.";
        return;
      }
      if (typeof motion.requestPermission === "function" && !window.isSecureContext) {
        shakeNoteEl.textContent = "Open the https link to enable shaking.";
        return;
      }
      try {
        if (typeof motion.requestPermission === "function") {
          const result = await motion.requestPermission();
          if (result !== "granted") {
            shakeNoteEl.textContent = "Shaking is off.";
            return;
          }
        }
      } catch (error) {
        shakeNoteEl.textContent = "Shaking is off.";
        return;
      }
      if (shaking) {
        return;
      }
      window.addEventListener("devicemotion", onMotion);
      shaking = true;
      nameEl.readOnly = true;
      codeEl.readOnly = true;
      enableShakeEl.hidden = true;
      dismissKeyboard();
      shakeNoteEl.textContent = "Shaking is on.";
      if (!inLobby) {
        joinEl.hidden = false;
      }
    }

    document.getElementById("enable-shake").addEventListener("click", () => {
      enableShaking();
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") {
        lastShakeAt = 0;
      }
    });
    nameEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        send({ type: "create", name: nameEl.value, shaking: true });
      }
    });
    codeEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        send({ type: "join", name: nameEl.value, code: codeEl.value, shaking: true });
      }
    });

    function scheduleReconnect() {
      statusEl.textContent = "Reconnecting";
      if (retryTimer !== null) {
        return;
      }
      retryTimer = setTimeout(() => {
        retryTimer = null;
        connect();
      }, 1000);
    }

    function connect() {
      statusEl.textContent = "Connecting";
      const protocol = location.protocol === "https:" ? "wss:" : "ws:";
      const next = new WebSocket(protocol + "//" + location.host + "/ws");
      socket = next;

      next.addEventListener("message", (event) => {
        if (next !== socket) {
          return;
        }
        let message;
        try {
          message = JSON.parse(event.data);
        } catch (error) {
          return;
        }
        if (message.type === "hello") {
          statusEl.textContent = "Connected";
        } else if (message.type === "lobby") {
          showLobby(message);
        } else if (message.type === "rematched") {
          showNotice(rematchText(message));
        } else if (message.type === "left") {
          inLobby = false;
          showJoin();
        } else if (message.type === "error") {
          errorEl.textContent = message.message || "Something went wrong.";
        }
      });

      next.addEventListener("close", () => {
        if (next !== socket) {
          return;
        }
        if (inLobby) {
          inLobby = false;
          showJoin();
          errorEl.textContent = "Connection lost. Join the lobby again.";
        }
        scheduleReconnect();
      });

      next.addEventListener("error", () => {
        if (next === socket) {
          statusEl.textContent = "Reconnecting";
        }
      });
    }

    connect();
  </script>
</body>
</html>
"""


def create_app() -> web.Application:
    app = web.Application()
    app["book"] = LobbyBook()
    app["sockets"] = {}
    app["bridge"] = Bridge()
    app.on_cleanup.append(close_bridge)
    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket)
    return app


async def close_bridge(app: web.Application) -> None:
    app["bridge"].close()


async def index(_request: web.Request) -> web.Response:
    return web.Response(text=PAGE, content_type="text/html", charset="utf-8")


async def websocket(request: web.Request) -> web.WebSocketResponse:
    socket = web.WebSocketResponse(heartbeat=20)
    await socket.prepare(request)
    peer = request.remote or "unknown"
    player_id: str | None = None
    log.info("phone connected from %s", peer)
    try:
        await socket.send_str(json.dumps({"type": "hello"}))
        async for message in socket:
            if message.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED, WSMsgType.ERROR):
                break
            if message.type != WSMsgType.TEXT:
                continue
            player_id = await handle_text(request.app, socket, player_id, message.data)
    finally:
        if player_id is not None:
            await drop_player(request.app, player_id)
        log.info("phone disconnected from %s", peer)
    return socket


async def handle_text(app: web.Application, socket: web.WebSocketResponse, player_id: str | None, raw: str) -> str | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        await send_error(socket, "That message could not be read.")
        return player_id
    if not isinstance(payload, dict):
        await send_error(socket, "That message could not be read.")
        return player_id

    kind = payload.get("type")
    book: LobbyBook = app["book"]
    try:
        if kind in ("create", "join"):
            if payload.get("shaking") is not True:
                raise LobbyError("Enable shaking before joining a lobby.")
            if kind == "create":
                new_id, code = book.create(payload.get("name"))
            else:
                new_id, code = book.join(payload.get("code"), payload.get("name"))
            app["sockets"][new_id] = socket
            previous = player_id
            player_id = new_id
            if previous is not None:
                await drop_player(app, previous)
            log.info("player %s entered lobby %s", player_id, code)
            await broadcast(app, code)
        elif kind == "start":
            if player_id is None:
                raise LobbyError("You are not in a lobby.")
            code = book.start(player_id)
            log.info("lobby %s started", code)
            await broadcast(app, code)
            app.setdefault("round_tasks", {})[code] = asyncio.create_task(finish_when_due(app, code))
            app.setdefault("pull_tasks", {})[code] = asyncio.create_task(fade_pull(app, code))
            app.setdefault("chase_tasks", {})[code] = asyncio.create_task(chase_round(app, code))
        elif kind == "rematch":
            if player_id is None:
                raise LobbyError("You are not in a lobby.")
            code = book.rematch(player_id)
            log.info("rematch opened as lobby %s", code)
            await notify(app, code, {"type": "rematched", "code": code, "by": book.creator_name(code)})
            await broadcast(app, code)
        elif kind == "shakes":
            if player_id is None:
                raise LobbyError("You are not in a lobby.")
            code, changed = book.record_shakes(player_id, payload.get("total"))
            if changed:
                await broadcast(app, code)
        elif kind == "leave":
            if player_id is not None:
                await drop_player(app, player_id)
                player_id = None
            await socket.send_str(json.dumps({"type": "left"}))
        else:
            await send_error(socket, "That request was not recognized.")
    except LobbyError as error:
        await send_error(socket, error.message)
    return player_id


async def chase_round(app: web.Application, code: str) -> None:
    book: LobbyBook = app["book"]

    async def publish() -> None:
        if book.member_ids(code):
            await broadcast(app, code)

    try:
        await follow(book, app["bridge"], code, publish)
    except Exception:
        log.exception("lobby %s chase stopped", code)
        book.finish_draw(code)
    finally:
        app.setdefault("chase_tasks", {}).pop(code, None)
    if book.member_ids(code):
        await broadcast(app, code)


async def finish_when_due(app: web.Application, code: str) -> None:
    book: LobbyBook = app["book"]
    try:
        while True:
            deadline = book.deadline(code)
            if deadline is None:
                return
            delay = deadline - time.time()
            if delay > 0:
                await asyncio.sleep(min(delay, 0.25))
                continue
            if book.finish_if_due(code):
                log.info("lobby %s finished", code)
                await broadcast(app, code)
                return
            await asyncio.sleep(0.05)
    finally:
        app.setdefault("round_tasks", {}).pop(code, None)


async def fade_pull(app: web.Application, code: str) -> None:
    book: LobbyBook = app["book"]
    try:
        while True:
            await asyncio.sleep(PULL_TICK_SECONDS)
            if not book.pull_round_open(code):
                return
            if book.decay_pull(code):
                await broadcast(app, code)
    finally:
        app.setdefault("pull_tasks", {}).pop(code, None)


async def drop_player(app: web.Application, player_id: str) -> None:
    app["sockets"].pop(player_id, None)
    code = app["book"].leave(player_id)
    if code is not None:
        await broadcast(app, code)


async def broadcast(app: web.Application, code: str) -> None:
    book: LobbyBook = app["book"]
    sockets: dict[str, web.WebSocketResponse] = app["sockets"]
    for player_id in book.member_ids(code):
        destination = sockets.get(player_id)
        if destination is None or destination.closed:
            continue
        try:
            await destination.send_str(json.dumps(book.snapshot(code, player_id)))
        except ClientConnectionError:
            continue


async def notify(app: web.Application, code: str, payload: dict) -> None:
    """Send the same message to everyone in a lobby."""
    sockets: dict[str, web.WebSocketResponse] = app["sockets"]
    text = json.dumps(payload)
    for player_id in app["book"].member_ids(code):
        destination = sockets.get(player_id)
        if destination is None or destination.closed:
            continue
        try:
            await destination.send_str(text)
        except ClientConnectionError:
            continue


async def send_error(socket: web.WebSocketResponse, message: str) -> None:
    if not socket.closed:
        await socket.send_str(json.dumps({"type": "error", "message": message}))
