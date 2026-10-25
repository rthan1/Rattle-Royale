"""Phone connection, lobbies, and a 45-second chase.

A phone can create or join a lobby of up to eight players. Each player gets a
seat and a floor mark. The creator starts the game. A 3-second countdown runs
before shakes count, so the host cannot start early. The page draws the arena
and the robot pose from the server. Shakes then add pull, and the robot creeps
toward the leader when the Arduino is online. Reaching a mark wins. If time
runs out, the closest player wins.
"""

import asyncio
import io
import json
import logging
import time
from pathlib import Path

import segno
from aiohttp import ClientConnectionError, WSMsgType, web

from server.bridge import Bridge
from server.chase import follow
from server.lobby import PULL_TICK_SECONDS, LobbyBook, LobbyError

HOST = "0.0.0.0"
PORT = 8080
ROBOT_IMAGE = Path(__file__).resolve().parent / "static" / "robot.svg"
QR_MAX_LENGTH = 200

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
      border: none;
      border-radius: 0.6rem;
      background: #2c2c2c;
      color: #f4f4f4;
      touch-action: manipulation;
      cursor: pointer;
    }
    button:active { transform: scale(0.98); }
    button.primary { background: #ffc14d; color: #111; font-weight: bold; }
    button.quiet { background: transparent; color: #bbb; border: 1px solid #444; font-size: 1rem; padding: 0.65rem; }
    #clock { font-size: 3.5rem; font-weight: bold; margin: 0 0 0.5rem; font-variant-numeric: tabular-nums; }
    #clock.ready { color: #ffc14d; font-size: 5rem; line-height: 1.1; }
    #clock.go { color: #7be495; font-size: 4.5rem; line-height: 1.1; }
    #clock.low { color: #ff7a7a; }
    #result { font-size: 2.4rem; font-weight: bold; margin: 0 0 0.25rem; }
    #result.won { color: #7be495; }
    #result-detail { margin: 0 0 1rem; color: #aaa; }
    #error { min-height: 1.2rem; margin: 0; color: #ffb4b4; text-align: center; }
    #waiting { margin: 0 0 0.9rem; color: #aaa; }
    #lobby { text-align: center; }
    #lobby-code {
      font-size: 3rem;
      letter-spacing: 0.18rem;
      margin: 0 0 0.25rem;
    }
    #lobby-count { margin: 0 0 1rem; color: #aaa; }
    #lobby.compact #lobby-code,
    #lobby.compact #lobby-count,
    #lobby.compact #your-seat { display: none; }
    #notice { font-size: 1.15rem; margin: 0 0 1rem; color: #b4e0ff; }
    #your-seat { font-size: 2rem; margin: 0 0 0.25rem; }
    #your-mark { margin: 0 0 0.35rem; color: #aaa; }
    #chase { font-size: 1.25rem; margin: 0 0 0.75rem; }
    #arena-caption { font-size: 1.1rem; margin: 0 0 0.4rem; color: #ffc14d; }
    #arena {
      width: min(100%, calc(100vh - 17rem));
      width: min(100%, calc(100dvh - 17rem));
      height: auto;
      display: block;
      margin: 0 auto 1rem;
      background: #1c1c1c;
      border-radius: 0.5rem;
    }
    #players { list-style: none; padding: 0; margin: 0 0 1.25rem; font-size: 1.15rem; text-align: left; }
    #players li {
      display: flex;
      align-items: center;
      gap: 0.6rem;
      padding: 0.45rem 0.6rem;
      margin: 0 0 0.35rem;
      border-radius: 0.5rem;
      background: #1c1c1c;
      border-left: 4px solid transparent;
    }
    #players li.you { background: #1d2733; }
    #players li.target { border-left-color: #e24b4b; }
    #players .seat {
      flex: none;
      width: 1.6rem;
      height: 1.6rem;
      line-height: 1.6rem;
      border-radius: 50%;
      background: #dedede;
      color: #111;
      font-size: 0.85rem;
      font-weight: bold;
      text-align: center;
    }
    #players li.target .seat { background: #e24b4b; }
    #players .who { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    #players .tag { flex: none; font-size: 0.75rem; color: #ff9a9a; text-transform: uppercase; letter-spacing: 0.05rem; }
    #players .bar { flex: none; width: 4.5rem; height: 0.5rem; border-radius: 0.25rem; background: #333; overflow: hidden; }
    #players .bar span { display: block; height: 100%; background: #ffc14d; }
    #players .num { flex: none; min-width: 2ch; text-align: right; font-variant-numeric: tabular-nums; color: #ccc; }
    #shakes { font-size: 1.6rem; margin: 0 0 0.4rem; text-align: center; }
    #shakes.pulse { animation: shake-pulse 0.25s ease-out; }
    @keyframes shake-pulse {
      from { transform: scale(1.25); color: #ffc14d; }
      to { transform: scale(1); color: inherit; }
    }
    @media (prefers-reduced-motion: reduce) {
      #shakes.pulse { animation: none; }
    }
    #invite { margin: 0 0 1rem; }
    #invite-qr { display: block; width: 7.5rem; height: 7.5rem; margin: 0 auto 0.6rem; border-radius: 0.4rem; background: #fff; }
    #host-tip { margin: 0 0 0.75rem; color: #ccc; font-size: 0.95rem; }
    #host-tip.offline { color: #ff9a9a; }
    #shake-note { margin: 0 0 0.9rem; color: #aaa; font-size: 0.95rem; text-align: center; }
    #open-lobby { margin: 0 0 1.1rem; padding: 0.8rem; border-radius: 0.6rem; background: #1c1c1c; text-align: center; }
    #open-lobby-code { font-size: 2.6rem; font-weight: bold; letter-spacing: 0.18rem; margin: 0 0 0.2rem; }
    #open-lobby-label { margin: 0; color: #bbb; font-size: 0.95rem; }
  </style>
</head>
<body>
  <main>
    <p id="status">Connecting</p>
    <p id="shakes" hidden>Shakes: 0</p>
    <button id="enable-shake" type="button" class="primary">Enable shaking</button>
    <p id="shake-note">Enable shaking to create or join a lobby.</p>
    <div id="open-lobby" hidden>
      <p id="open-lobby-code"></p>
      <p id="open-lobby-label"></p>
    </div>
    <section id="join" hidden>
      <label for="name">Name</label>
      <input id="name" maxlength="20" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" enterkeyhint="done">
      <button id="create" type="button" class="primary">Create lobby</button>
      <label for="code">Lobby code</label>
      <input id="code" maxlength="4" autocomplete="off" autocorrect="off" autocapitalize="characters" spellcheck="false" enterkeyhint="go">
      <button id="join-lobby" type="button" class="primary">Join lobby</button>
    </section>
    <section id="lobby" hidden>
      <p id="notice" hidden></p>
      <p id="clock" hidden></p>
      <p id="result" hidden></p>
      <p id="result-detail" hidden></p>
      <p id="lobby-code"></p>
      <p id="lobby-count"></p>
      <div id="invite" hidden>
        <img id="invite-qr" alt="QR code to join this lobby">
        <button id="share" type="button" class="quiet">Share invite link</button>
      </div>
      <p id="your-seat"></p>
      <p id="your-mark"></p>
      <p id="host-tip" hidden></p>
      <button id="start" type="button" class="primary" hidden>Start game</button>
      <button id="rematch" type="button" class="primary" hidden>Rematch</button>
      <p id="waiting" hidden>Waiting for the creator to start</p>
      <p id="chase" hidden></p>
      <p id="arena-caption" hidden></p>
      <canvas id="arena" width="320" height="320" hidden></canvas>
      <ul id="players"></ul>
      <button id="leave" type="button" class="quiet">Leave lobby</button>
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
    let openLobby = null;
    let suggestedCode = "";
    let audio = null;

    let audioPrimed = false;

    function unlockAudio() {
      try {
        if (navigator.audioSession) {
          navigator.audioSession.type = "playback";
        }
        const Context = window.AudioContext || window.webkitAudioContext;
        if (!audio && Context) {
          audio = new Context();
        }
        if (!audio) {
          return;
        }
        if (audio.state !== "running") {
          audio.resume();
        }
        if (!audioPrimed) {
          const silence = audio.createBufferSource();
          silence.buffer = audio.createBuffer(1, 1, audio.sampleRate);
          silence.connect(audio.destination);
          silence.start(0);
          audioPrimed = true;
        }
      } catch (error) {
        audio = null;
      }
    }

    function beep(frequency, ms, volume = 0.4) {
      if (!audio) {
        return;
      }
      if (audio.state !== "running") {
        audio.resume().catch(() => {});
        return;
      }
      const start = audio.currentTime;
      const end = start + ms / 1000;
      const tone = audio.createOscillator();
      const gain = audio.createGain();
      tone.type = "triangle";
      tone.frequency.value = frequency;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(volume, start + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, end);
      tone.connect(gain).connect(audio.destination);
      tone.start(start);
      tone.stop(end);
    }

    ["touchend", "click"].forEach((kind) => document.addEventListener(kind, unlockAudio, { passive: true }));
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && audio && audio.state !== "running") {
        audio.resume().catch(() => {});
      }
    });

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
      keepAwake(false);
      refreshChrome();
    }

    let showingReady = false;
    const LOW_TIME_SECONDS = 10;

    let wakeLock = null;
    let wakeWanted = false;
    let wakePending = false;

    async function keepAwake(on) {
      wakeWanted = on;
      if (!on) {
        const lock = wakeLock;
        wakeLock = null;
        if (lock) {
          try {
            await lock.release();
          } catch (error) {
            return;
          }
        }
        return;
      }
      if (wakeLock || wakePending || !("wakeLock" in navigator) || document.visibilityState !== "visible") {
        return;
      }
      wakePending = true;
      try {
        const lock = await navigator.wakeLock.request("screen");
        lock.addEventListener("release", () => {
          if (wakeLock === lock) {
            wakeLock = null;
          }
        });
        wakeLock = lock;
        if (!wakeWanted) {
          keepAwake(false);
        }
      } catch (error) {
        wakeLock = null;
      } finally {
        wakePending = false;
      }
    }

    function refreshChrome() {
      statusEl.hidden = inLobby && statusEl.textContent === "Connected";
      shakeNoteEl.hidden = inLobby && shaking;
      showOpenLobby();
    }

    function showOpenLobby() {
      const lobby = openLobby;
      document.getElementById("open-lobby").hidden = inLobby || !lobby;
      document.getElementById("create").hidden = Boolean(lobby);
      if (!lobby) {
        return;
      }
      document.getElementById("open-lobby-code").textContent = lobby.code;
      const label = document.getElementById("open-lobby-label");
      if (lobby.started) {
        label.textContent = "A game is running. If the host starts a rematch, its new code shows up here.";
      } else if (lobby.players >= lobby.max) {
        label.textContent = "Lobby full: " + lobby.players + " of " + lobby.max + " players";
      } else {
        label.textContent = "Open lobby: " + lobby.players + " of " + lobby.max + " players. Enter your name to join.";
      }
      const joinable = !lobby.started && lobby.players < lobby.max;
      if (joinable && (codeEl.value === "" || codeEl.value === suggestedCode)) {
        codeEl.value = lobby.code;
        suggestedCode = lobby.code;
      }
    }

    function setStatus(text) {
      statusEl.textContent = text;
      refreshChrome();
    }

    const GO_MS = 900;
    let lastCue = null;
    let goUntil = null;

    function runCountdown() {
      stopCountdown();
      lastCue = null;
      goUntil = null;
      const clock = document.getElementById("clock");
      function tick() {
        const now = Date.now();
        const ready = roundOpensAt !== null && now < roundOpensAt;
        clock.classList.toggle("ready", ready);
        if (ready) {
          showingReady = true;
          clock.classList.remove("low");
          const count = Math.max(1, Math.ceil((roundOpensAt - now) / 1000));
          if (count !== lastCue) {
            lastCue = count;
            beep(660, 140);
          }
          clock.textContent = String(count);
          return;
        }
        if (showingReady && lobbyMessage) {
          showingReady = false;
          lastCue = null;
          goUntil = now + GO_MS;
          beep(990, 450);
          clock.classList.add("go");
          clock.textContent = "GO!";
          showLobby(lobbyMessage);
          return;
        }
        if (goUntil !== null && now < goUntil) {
          clock.classList.add("go");
          clock.classList.remove("low");
          clock.textContent = "GO!";
          return;
        }
        clock.classList.remove("go");
        const left = roundEndsAt === null ? 0 : Math.max(0, Math.ceil((roundEndsAt - now) / 1000));
        if (left > 0 && left <= 3 && left !== lastCue) {
          lastCue = left;
          beep(520, 90, 0.3);
        }
        clock.classList.toggle("low", left <= LOW_TIME_SECONDS);
        clock.textContent = left + "s";
        if (left <= 0) {
          stopCountdown();
        }
      }
      tick();
      countdownTimer = setInterval(tick, 200);
    }

    const GLIDE_MIN_MS = 250;
    const GLIDE_MAX_MS = 3000;
    const GLIDE_DEFAULT_MS = 1000;
    const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let arenaMessage = null;
    let robotShown = null;
    let robotGlide = null;
    let robotRound = null;
    let robotPoseAt = null;
    let robotGap = GLIDE_DEFAULT_MS;
    let robotFrame = null;
    const ARENA_SIZE = 320;
    const ROBOT_SIZE = 44;
    const NAME_INSET = 38;
    const NAME_MAX = 10;
    const robotImage = new Image();
    robotImage.addEventListener("load", () => {
      if (arenaMessage !== null && robotShown !== null) {
        paintArena(arenaMessage, robotShown);
      }
    });
    robotImage.src = "/robot.svg";

    let pulseFrame = null;

    function wantsPulse(message) {
      return !reduceMotion && message.started && !message.finished && (message.marks || []).some((mark) => mark.chased);
    }

    function stepPulse() {
      pulseFrame = null;
      if (arenaMessage === null || robotShown === null || !wantsPulse(arenaMessage)) {
        return;
      }
      if (robotGlide === null) {
        paintArena(arenaMessage, robotShown);
      }
      pulseFrame = requestAnimationFrame(stepPulse);
    }

    function samePlace(a, b) {
      return a.x === b.x && a.y === b.y && a.heading === b.heading;
    }

    function stopGlide() {
      if (robotFrame !== null) {
        cancelAnimationFrame(robotFrame);
        robotFrame = null;
      }
      robotGlide = null;
    }

    function stepGlide() {
      robotFrame = null;
      if (robotGlide === null || arenaMessage === null) {
        return;
      }
      const glide = robotGlide;
      const t = Math.min(1, (performance.now() - glide.startedAt) / glide.duration);
      const eased = (1 - Math.cos(Math.PI * t)) / 2;
      const turn = ((glide.to.heading - glide.from.heading) % 360 + 540) % 360 - 180;
      robotShown = {
        x: glide.from.x + (glide.to.x - glide.from.x) * eased,
        y: glide.from.y + (glide.to.y - glide.from.y) * eased,
        heading: glide.from.heading + turn * eased,
        known: glide.to.known,
      };
      paintArena(arenaMessage, robotShown);
      if (t < 1) {
        robotFrame = requestAnimationFrame(stepGlide);
      } else {
        robotGlide = null;
      }
    }

    function drawArena(message) {
      const canvas = document.getElementById("arena");
      const marks = message.marks || [];
      if (!message.pose || marks.length === 0) {
        canvas.hidden = true;
        stopGlide();
        if (pulseFrame !== null) {
          cancelAnimationFrame(pulseFrame);
          pulseFrame = null;
        }
        arenaMessage = null;
        robotShown = null;
        robotRound = null;
        return;
      }
      canvas.hidden = false;
      arenaMessage = message;
      const pose = message.pose;
      const target = { x: pose.x, y: pose.y, heading: pose.heading, known: pose.known };
      const round = message.code + ":" + message.opens_at;
      const now = performance.now();
      const goal = robotGlide !== null ? robotGlide.to : robotShown;
      if (robotShown === null || round !== robotRound || reduceMotion) {
        stopGlide();
        robotShown = target;
        robotRound = round;
        robotPoseAt = now;
        robotGap = GLIDE_DEFAULT_MS;
      } else if (!samePlace(goal, target)) {
        const gap = now - robotPoseAt;
        robotGap = gap > GLIDE_MAX_MS ? GLIDE_DEFAULT_MS : Math.max(GLIDE_MIN_MS, gap);
        robotPoseAt = now;
        robotGlide = { from: robotShown, to: target, startedAt: now, duration: robotGap };
        if (robotFrame === null) {
          robotFrame = requestAnimationFrame(stepGlide);
        }
      } else {
        goal.known = target.known;
        robotShown.known = target.known;
      }
      paintArena(message, robotShown);
      if (pulseFrame === null && wantsPulse(message)) {
        pulseFrame = requestAnimationFrame(stepPulse);
      }
    }

    function paintArena(message, pose) {
      const canvas = document.getElementById("arena");
      const ctx = canvas.getContext("2d");
      const size = ARENA_SIZE;
      const pixels = Math.round(size * Math.min(window.devicePixelRatio || 1, 3));
      if (canvas.width !== pixels) {
        canvas.width = pixels;
        canvas.height = pixels;
      }
      ctx.setTransform(pixels / size, 0, 0, pixels / size, 0, 0);
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
      const marks = message.marks || [];
      const live = message.started && !message.finished;
      const target = live ? marks.find((mark) => mark.chased && mark.angle != null) : null;
      if (target) {
        const aim = target.angle * Math.PI / 180;
        const spot = point(radius * Math.cos(aim), radius * Math.sin(aim));
        const from = point(pose.x, pose.y);
        const wave = reduceMotion ? 0.5 : (Math.sin(performance.now() / 250) + 1) / 2;
        ctx.save();
        ctx.strokeStyle = "#e24b4b";
        ctx.lineWidth = 2;
        ctx.globalAlpha = 0.7;
        ctx.setLineDash([6, 6]);
        ctx.beginPath();
        ctx.moveTo(from[0], from[1]);
        ctx.lineTo(spot[0], spot[1]);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.lineWidth = 3;
        ctx.globalAlpha = 0.25 + 0.5 * (1 - wave);
        ctx.beginPath();
        ctx.arc(spot[0], spot[1], 16 + 5 * wave, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      }
      marks.forEach((mark) => {
        if (mark.angle == null) {
          return;
        }
        const radians = mark.angle * Math.PI / 180;
        const spot = point(radius * Math.cos(radians), radius * Math.sin(radians));
        ctx.beginPath();
        ctx.arc(spot[0], spot[1], 12, 0, Math.PI * 2);
        ctx.fillStyle = mark.chased ? "#e24b4b" : "#dedede";
        ctx.fill();
        if (mark.you) {
          ctx.lineWidth = 3;
          ctx.strokeStyle = "#8ec8ff";
          ctx.stroke();
        }
        ctx.fillStyle = "#111";
        ctx.font = "bold 12px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(String(mark.seat), spot[0], spot[1]);
        if (mark.name) {
          const label = point((radius - NAME_INSET) * Math.cos(radians), (radius - NAME_INSET) * Math.sin(radians));
          const name = mark.name.length > NAME_MAX ? mark.name.slice(0, NAME_MAX - 1) + "…" : mark.name;
          ctx.font = "bold 11px sans-serif";
          ctx.lineJoin = "round";
          ctx.lineWidth = 3;
          ctx.strokeStyle = "#1c1c1c";
          ctx.strokeText(name, label[0], label[1]);
          ctx.fillStyle = mark.you ? "#8ec8ff" : "#dedede";
          ctx.fillText(name, label[0], label[1]);
        }
      });
      const robot = point(pose.x, pose.y);
      const edge = ROBOT_SIZE / 2;
      ctx.save();
      ctx.translate(robot[0], robot[1]);
      ctx.globalAlpha = pose.known ? 1 : 0.45;
      if (robotImage.complete && robotImage.naturalWidth > 0) {
        ctx.drawImage(robotImage, -edge, -edge, ROBOT_SIZE, ROBOT_SIZE);
      } else {
        ctx.beginPath();
        ctx.arc(0, 0, edge - 4, 0, Math.PI * 2);
        ctx.fillStyle = "#5aa9e6";
        ctx.fill();
      }
      ctx.restore();
    }

    function showLobby(message) {
      inLobby = true;
      lobbyMessage = message;
      const nowPlaying = message.started && !message.finished;
      if (nowPlaying && !playing) {
        resetShakes();
        showNotice("");
        window.scrollTo(0, 0);
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
      lobbyEl.classList.toggle("compact", message.started);
      document.getElementById("lobby-code").textContent = message.code;
      document.getElementById("lobby-count").textContent =
        message.players.length + " of " + message.max;
      document.getElementById("start").hidden = !(message.creator && !message.started);
      document.getElementById("rematch").hidden = !(message.creator && message.finished);
      const invite = document.getElementById("invite");
      invite.hidden = message.started || message.players.length >= message.max;
      if (!invite.hidden) {
        inviteLink = (message.public_url || location.origin) + "/?code=" + encodeURIComponent(message.code);
        const qr = document.getElementById("invite-qr");
        const source = "/qr.svg?data=" + encodeURIComponent(inviteLink);
        if (qr.getAttribute("src") !== source) {
          qr.setAttribute("src", source);
        }
      }
      const tip = document.getElementById("host-tip");
      const robotOffline = message.robot_online === false;
      tip.hidden = !message.creator || message.started;
      tip.classList.toggle("offline", robotOffline);
      tip.textContent = robotOffline
        ? "Robot offline. The round will run, but the robot won't move."
        : "Robot ready. Put it on the center mark, facing seat 0, then start.";
      const waiting = document.getElementById("waiting");
      waiting.hidden = message.creator || (message.started && !message.finished);
      waiting.textContent = message.finished
        ? "Waiting for the creator to start a rematch"
        : "Waiting for the creator to start";
      document.getElementById("leave").hidden = playing;
      const mine = message.players.find((player) => player.you);
      document.getElementById("your-seat").textContent = mine ? "You are seat " + mine.seat : "";
      document.getElementById("your-mark").textContent = !mine
        ? ""
        : message.last_match
          ? "Your mark appears when the game starts"
          : "Stand on mark " + mine.seat;
      const chase = document.getElementById("chase");
      if (ready) {
        chase.hidden = false;
        chase.textContent = "Get ready";
      } else if (message.started && !message.finished) {
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
      if (message.started && !message.finished && !ready && message.robot_online === false) {
        chase.textContent = "Robot offline, so it isn't moving";
      }
      const clock = document.getElementById("clock");
      const result = document.getElementById("result");
      const resultDetail = document.getElementById("result-detail");
      if (playing) {
        clock.hidden = false;
        result.hidden = true;
        result.textContent = "";
        resultDetail.hidden = true;
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
        const outcome = resultFor(message, mine);
        result.hidden = false;
        result.textContent = outcome.headline;
        result.classList.toggle("won", outcome.won);
        resultDetail.hidden = !outcome.detail;
        resultDetail.textContent = outcome.detail;
        const finishKey = message.code + ":" + message.ends_at;
        if (celebrated !== finishKey) {
          beep(outcome.won ? 880 : 300, 500);
          if (outcome.won && navigator.vibrate) {
            navigator.vibrate([120, 60, 240]);
          }
        }
        celebrated = finishKey;
      } else {
        stopCountdown();
        clock.hidden = true;
        result.hidden = true;
        result.textContent = "";
        resultDetail.hidden = true;
      }
      const list = document.getElementById("players");
      list.replaceChildren();
      const topPull = Math.max(1, ...message.players.map((player) => Number(player.pull) || 0));
      message.players.forEach((player) => {
        list.append(playerRow(player, message.started, topPull));
      });
      drawArena(message);
      const caption = document.getElementById("arena-caption");
      const captionText = arenaCaption(message, ready);
      caption.textContent = captionText;
      caption.hidden = document.getElementById("arena").hidden || !captionText;
      keepAwake(message.started && !message.finished);
      refreshChrome();
    }

    let celebrated = null;

    function resultFor(message, mine) {
      const winners = message.winners || [];
      let detail = "";
      if (message.reason === "arrival") {
        detail = "The robot reached them";
      } else if (message.reason === "clock") {
        detail = winners.length > 1 ? "Tied for closest when time ran out" : "Closest when time ran out";
      }
      if (message.reason === "draw" || winners.length === 0) {
        return { headline: "Draw", detail: "", won: false };
      }
      const youWon = Boolean(mine) && winners.includes(mine.name);
      if (youWon) {
        if (message.reason === "arrival") {
          detail = "The robot reached you";
        }
        const others = winners.filter((name) => name !== mine.name);
        if (others.length > 0) {
          detail = "With " + others.join(" & ") + ", closest when time ran out";
        }
        return { headline: others.length > 0 ? "You tied!" : "You won!", detail, won: true };
      }
      const headline = winners.length === 1 ? winners[0] + " won" : "Tie: " + winners.join(" & ");
      return { headline, detail, won: false };
    }

    function playerRow(player, started, topPull) {
      const item = document.createElement("li");
      item.classList.toggle("you", player.you);
      item.classList.toggle("target", started && player.chased);
      const seat = document.createElement("span");
      seat.className = "seat";
      seat.textContent = String(player.seat);
      const who = document.createElement("span");
      who.className = "who";
      who.textContent = player.you ? player.name + " (you)" : player.name;
      item.append(seat, who);
      if (!started) {
        return item;
      }
      if (player.chased) {
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = "target";
        item.append(tag);
      }
      const bar = document.createElement("span");
      bar.className = "bar";
      const fill = document.createElement("span");
      fill.style.width = Math.round(100 * Math.min(1, (Number(player.pull) || 0) / topPull)) + "%";
      bar.append(fill);
      const shakes = document.createElement("span");
      shakes.className = "num";
      shakes.textContent = String(player.shakes);
      item.append(bar, shakes);
      return item;
    }

    function arenaCaption(message, ready) {
      if (message.last_match) {
        const winners = message.last_match.winners || [];
        return winners.length === 0 ? "Last match: draw" : "Last match: " + winners.join(" & ") + " won";
      }
      if (!message.started || message.finished || ready) {
        return "";
      }
      const leaders = message.leaders || [];
      if (leaders.length === 0) {
        return "";
      }
      if (leaders.length > 1) {
        return leaders.length === message.players.length ? "Everyone is tied" : "Tied: " + leaders.join(" & ");
      }
      const mine = message.players.find((player) => player.you);
      return mine && mine.name === leaders[0] ? "You are winning" : leaders[0] + " is winning";
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
    let inviteLink = "";
    document.getElementById("share").addEventListener("click", async () => {
      const button = document.getElementById("share");
      if (navigator.share) {
        try {
          await navigator.share({ title: "Join my Rattle Royale lobby", url: inviteLink });
          return;
        } catch (error) {
          if (error && error.name === "AbortError") {
            return;
          }
        }
      }
      try {
        await navigator.clipboard.writeText(inviteLink);
        button.textContent = "Link copied";
      } catch (error) {
        button.textContent = inviteLink;
      }
      setTimeout(() => {
        button.textContent = "Share invite link";
      }, 2000);
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

    const linkCode = new URLSearchParams(location.search).get("code");
    if (linkCode) {
      codeEl.value = linkCode.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 4);
    }

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
      shakesEl.classList.remove("pulse");
      void shakesEl.offsetWidth;
      shakesEl.classList.add("pulse");
      if (navigator.vibrate) {
        navigator.vibrate(15);
      }
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
      unlockAudio();
      setTimeout(() => beep(880, 120), 60);
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
      } else if (wakeWanted) {
        keepAwake(true);
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
      setStatus("Reconnecting");
      if (retryTimer !== null) {
        return;
      }
      retryTimer = setTimeout(() => {
        retryTimer = null;
        connect();
      }, 1000);
    }

    function connect() {
      setStatus("Connecting");
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
          setStatus("Connected");
        } else if (message.type === "lobby") {
          showLobby(message);
        } else if (message.type === "open_lobby") {
          openLobby = message.lobby;
          showOpenLobby();
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
          setStatus("Reconnecting");
        }
      });
    }

    connect();
  </script>
</body>
</html>
"""


def create_app(public_url: str | None = None) -> web.Application:
    """public_url is the address phones use, such as the ngrok link, for invites."""
    app = web.Application()
    app["public_url"] = public_url.rstrip("/") if public_url else None
    app["book"] = LobbyBook()
    app["sockets"] = {}
    app["watchers"] = set()
    app["bridge"] = Bridge()
    app.on_cleanup.append(close_bridge)
    app.router.add_get("/", index)
    app.router.add_get("/robot.svg", robot_image)
    app.router.add_get("/qr.svg", qr_image)
    app.router.add_get("/ws", websocket)
    return app


async def close_bridge(app: web.Application) -> None:
    app["bridge"].close()


async def index(_request: web.Request) -> web.Response:
    return web.Response(text=PAGE, content_type="text/html", charset="utf-8")


async def robot_image(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(ROBOT_IMAGE)


async def qr_image(request: web.Request) -> web.Response:
    """A QR code for an invite link, so phones can join by pointing a camera at it."""
    data = request.query.get("data", "")
    if not data.startswith(("http://", "https://")) or len(data) > QR_MAX_LENGTH:
        raise web.HTTPBadRequest(text="Send an http or https link of at most 200 characters.")
    buffer = io.BytesIO()
    segno.make(data, error="m").save(buffer, kind="svg", scale=4, border=2, dark="#111", light="#fff")
    return web.Response(body=buffer.getvalue(), content_type="image/svg+xml", headers={"Cache-Control": "max-age=3600"})


async def websocket(request: web.Request) -> web.WebSocketResponse:
    socket = web.WebSocketResponse(heartbeat=20)
    await socket.prepare(request)
    peer = request.remote or "unknown"
    player_id: str | None = None
    log.info("phone connected from %s", peer)
    request.app["watchers"].add(socket)
    try:
        await socket.send_str(json.dumps({"type": "hello"}))
        await socket.send_str(json.dumps(lobby_notice(request.app)))
        async for message in socket:
            if message.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED, WSMsgType.ERROR):
                break
            if message.type != WSMsgType.TEXT:
                continue
            player_id = await handle_text(request.app, socket, player_id, message.data)
    finally:
        request.app["watchers"].discard(socket)
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
            await socket.send_str(json.dumps(lobby_notice(app)))
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
    else:
        await announce(app)


def lobby_notice(app: web.Application) -> dict:
    return {"type": "open_lobby", "lobby": app["book"].open_lobby()}


async def announce(app: web.Application) -> None:
    """Tell phones that are not in the lobby about it, when its code, size, or state changes."""
    notice = lobby_notice(app)
    if notice == app.get("announced"):
        return
    app["announced"] = notice
    members = set(app["sockets"].values())
    text = json.dumps(notice)
    for destination in list(app["watchers"]):
        if destination in members or destination.closed:
            continue
        try:
            await destination.send_str(text)
        except ClientConnectionError:
            continue


async def broadcast(app: web.Application, code: str) -> None:
    book: LobbyBook = app["book"]
    sockets: dict[str, web.WebSocketResponse] = app["sockets"]
    for player_id in book.member_ids(code):
        destination = sockets.get(player_id)
        if destination is None or destination.closed:
            continue
        try:
            snapshot = book.snapshot(code, player_id)
            snapshot["robot_online"] = bool(app["bridge"].online)
            snapshot["public_url"] = app["public_url"]
            await destination.send_str(json.dumps(snapshot))
        except ClientConnectionError:
            continue
    await announce(app)


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
