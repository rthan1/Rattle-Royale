# Rattle Royale architecture

Rattle Royale is a party game for phones, with a two-motor robot on the bench. The running game is a lobby and a 45-second chase. Players open a page from the laptop, enable shaking, and join a lobby of up to 8 people. Each player gets a seat and a floor mark. The creator starts the round. Everyone shakes. The robot creeps toward whoever is shaking now. Reaching a mark wins. If the clock runs out first, the closest player wins, and players at the same distance tie.

During that round the server keeps a fading pull score and, when the Arduino is online, sends one short spin or drive at a time toward that player. Every phone shows the name. `server/bridge.py` opens the Arduino port. If `RATTLE_PORT` is unset, the round still runs and the robot stays still.

The phones do not drive motors. The laptop runs the page, the lobby, the clock, the scores, and the chase line. Campus Wi-Fi often blocks a phone from opening the laptop’s own address, so phones use an ngrok HTTPS tunnel to that same server. iOS also requires HTTPS before it will share motion data.

```text
Phones (up to 8)                         Laptop
Enable shaking, then join  --WebSocket--  Game server
    shake total during the round              lobby, seats, 45s clock, scores
                                              fading pull, chase, pose, winner
```

A round keeps a pose, asks the planner for one chunk, and sends that chunk through the bridge. The phone draws that pose on the arena. Before each round the host places the robot on the center mark by hand. Seats, marks, fading pull, and the chase line are in the running game.

| Piece | Where it runs | Now |
|---|---|---|
| Phone client | Browser on each phone | Join a lobby, show the seat and mark, count shakes, show pull, the chase line, the countdown, the arena, and the winner |
| Game server | Laptop, port 8080 | Rooms, names, seats, 3-second countdown, 45-second clock, shake scores, fading pull, chase target, pose, winner |
| ngrok | Laptop, forwarding to port 8080 | Public HTTPS address for phones |
| Pose | Same laptop | `server/pose.py` stores `x`, `y`, and heading. A round starts at home and updates the pose from each finished move |
| Motion planner | Same laptop | `server/planner.py` turns that pose and a mark into one short `SPIN` or `DRIVE`, or reports a reached mark. The chase loop calls it |
| Serial bridge | Same laptop, using pyserial | Opens `RATTLE_PORT` at startup. The chase sends one command and waits for the reply |
| Firmware | Arduino | `firmware/dual_motor` accepts `SPIN`, `DRIVE`, `STOP`, and `PING`. `drive_test` rolls the car. `spin_test` turns it in place |

## What already exists

The phone game lives in `server/`. Start it from the project folder with `python -m server`. It serves the page at `/` and a WebSocket at `/ws`. `requirements.txt` includes `aiohttp` for that server, `pyserial` for the Arduino link, and `segno` for invite QR codes. `server/bridge.py` is the only module that imports `pyserial`.

`server/lobby.py` assigns seats, locks each seat’s angle when the round starts, accepts shake totals, fades pull, and chooses the chase target. `server/test_lobby.py` and `server/test_pull.py` cover that. `server/test_bridge.py` covers the serial link with a fake port. `server/pose.py` stores the robot pose, and `server/test_pose.py` covers updates from a finished move. `server/planner.py` chooses the next chunk, and `server/test_planner.py` covers that choice. `server/chase.py` runs the loop during a round, and `server/test_chase.py` covers it with a fake robot. The page in `server/app.py` shows the seat, the mark, the pull, who is being chased, a drawing of the arena and the robot, and whether the win was by arrival or by the clock.

`ngrok.yml` points a public HTTPS address at `http://127.0.0.1:8080`. The phone page follows whatever address it was opened on, so the WebSocket uses the ngrok host when the page was opened through the tunnel.

The robot hardware is two 28BYJ-48 steppers, each on its own ULN2003 driver. `firmware/dual_motor` accepts motion commands. Set `RATTLE_PORT` to the board’s COM port before starting the server, and close the serial monitor first. The server keeps that port open and the chase sends chunks through it. If the variable is unset, or the board does not answer, the server logs that the robot is offline, the chase holds still, and the lobby still runs.

- Motor 1 uses Arduino pins 4, 5, 6, and 7.
- Motor 2 uses Arduino pins A0, A1, A2, and A3.
- Both driver grounds share the Arduino ground. Driver VCC should come from an external 5V supply, because both motors draw current at the same time.
- About 4096 half-steps is one revolution of a 28BYJ-48. At 3 ms per step, one wheel revolution takes about 12 seconds.
- `firmware/motor_test` exercises one motor on pins A0–A3. `firmware/stepper_driver` exercises one motor on pins 8–11, which is an older single-motor wiring, not motor 1 on the car.
- `firmware/drive_test` steps both car motors the same way and keeps going. On the bench, that rolls the car.
- `firmware/spin_test` steps motor 1 forward and motor 2 backward, the opposite of the drive test, so the car turns in place.
- `firmware/dual_motor` is the game sketch. At 115200 baud it reads `PING`, `STOP`, `SPIN`, and `DRIVE`, steps both motors on the same tick, waits 3 ms once per step, and releases the coils when the chunk ends. A step count is 1 through 16000. `DRIVE` direction `1` rolls the car away from seat 0. `DRIVE` direction `-1` rolls toward seat 0. `SPIN` direction `1` turns from seat 0 toward seat 1. `SPIN` direction `-1` turns the other way.

## How a round feels

1. The player opens the page and taps **Enable shaking**. The name and lobby controls stay hidden until that succeeds. A phone with no motion sensor never gets them.
2. They enter a name and either create a lobby or join with a 4-character code. The lobby lists every name and seat, and it draws the arena. The robot is in the middle. Each current player is a mark on the circle, and those marks move when someone joins or leaves.
3. The creator taps **Start game**. Seats lock, and each seat gets the angle it will keep for the round. A 3-second countdown runs. Shakes during it do not count, and the robot stays still. The host places the robot on the center mark, pointed at seat 0, before this.
4. When the countdown hits zero, the 45-second chase begins. Shakes add to that player’s score only while it is running. The same shakes add pull. Pull fades while the round is open, and the phone with the strongest pull is the one the robot chases. The list on every phone shows the same scores and pull. The personal shake total is hidden on the join screen and appears once the chase has begun. The arena keeps drawing, now from the pose the server reports after each chunk.
5. The round ends when the robot’s pose comes within 25 mm of a mark, or when the clock runs out. Arrival names that player. The clock names the closest player, or everyone tied for closest. The page says which one happened. The leave button is hidden during the 45 seconds and comes back with the result.
6. Leaving the lobby removes that player and sets their phone’s shake count back to 0. After the result, the creator can tap **Rematch**. Everyone still there moves to a fresh lobby under a new code, with scores and seats reset, and new players can join with that code before the next start. The arena stays on the result of the round that just ended, robot included, until that next start puts the robot back in the middle and lays the marks out for whoever is there.

One player is enough to start. The creator is the person who created the lobby. If they leave and someone is still in it, the next person in the list becomes the creator.

## Phone client

A mobile web page served by the laptop. Players join by opening the ngrok HTTPS link. A native app is unnecessary.

The page asks for motion permission, takes a name and a lobby code, shows the seat and floor mark, counts shakes during the chase, and shows the arena, the scores, the pull, who the robot is chasing, the countdown, and the winner.

### Enable shaking

Shake detection uses the phone’s accelerometer through browser motion events.

- iOS only exposes motion data on an HTTPS page, and only after a tap that calls the permission request. The ngrok address is that HTTPS page.
- Android can read motion without that extra permission. The same page still asks everyone to tap **Enable shaking**.
- Create and join stay unavailable until shaking is on. The server also refuses a create or join that does not say shaking is enabled.
- If the browser has no motion API, the page says this phone cannot shake, and the lobby controls stay hidden.
- Turning shaking on closes the keyboard. Name and code are recorded by the page rather than by the keyboard’s own typing history, so an iPhone is less likely to pop up “Undo Typing” when the phone is shaken.

### Join a room

After shaking is enabled, the page asks for a display name and, to join an existing lobby, a code.

- The code is 4 characters from an alphabet that skips look-alike letters, so it can be read aloud.
- The display name is what the lobby list shows. The server assigns the seat. The creator is seat 0. The next player is seat 1, and so on.
- Before the round starts, a player who leaves is removed and the later seats pack down. After the start, a seat number stays put when someone leaves.
- The page shows “You are seat 3” and “Stand on mark 3” in the lobby. Once the round starts it also draws the circle, the marks, and the robot.
- Empty names, names longer than 20 characters, duplicate names in the same lobby, a full lobby (8 players), an unknown code, and a join after the start get a clear message on the page.
- A refresh or a dropped connection removes the player. The page does not resume the same seat.
- The page shows connecting and reconnecting. After a disconnect it returns to the join screen.

### Shake detection

The phone counts shakes locally and sends its running total for this round to the server when the count increases. It sends the total, not a claim that it is winning.

The strength of a reading is the magnitude of acceleration including gravity, in meters per second squared. Rest is about one gravity. A reading at or above a threshold of 15 counts. While the phone stays that strong, another shake is added about every 150 milliseconds, so a continuous rattle keeps scoring. The phone stops adding when the countdown reaches zero.

The phone sends totals only while the chase window is open. Shakes before the start, during the 3-second countdown, and after zero stay off the score. If the tab is hidden, counting pauses. The shake total on the phone is reset when the player leaves the lobby, and a new round starts that phone from zero.

The server is given a short grace, about half a second after zero, to accept the last total that was already sent. The number on the phone and the number used to pick the winner are the same total.

### Scoreboard

The lobby draws the arena as soon as it exists. The robot starts in the middle, and the marks follow joins and leaves. A rematch keeps the previous result on that drawing until the next start. Each mark shows its seat number and the player's name, shortened past 10 characters, so someone who joins the rematch can read the last match. The held names stay even if that player has left. A caption above the arena reads “Last match: Bea won” (or “Last match: draw”) while that result is held. During the chase the caption names who would win if the clock ran out now: the players whose marks are closest to the robot. It reads “Bea is winning”, “You are winning” on that player’s own phone, “Tied: Ada & Bea”, or “Everyone is tied”, which is how every round begins with the robot at home. It is hidden during the countdown and once the result shows. During the countdown the page says “Get ready” and shows the seconds left before shakes count. During the chase it shows every player’s name, seat, shake count, and pull, ordered by pull. The local player’s row is marked. The chased row is marked with the word “chased”. A line above the list says “The robot is chasing” that name, “The robot is coming for you” on that player’s own phone, or “The robot is holding still” when nobody has pull. A square arena shows the marks and the robot. The robot is drawn from the pose in the latest server message: `x`, `y`, and heading. It is a robot picture that stays upright and fades when the pose is unknown. The pose changes when a chunk finishes, which is when the server knows the new pose. The page glides the robot to it over about the time between updates, turning the short way. A new round, or a phone set to reduce motion, places it without a glide. A countdown shows the time left in the chase, using the server’s end timestamp.

The robot picture, `server/static/robot.svg`, is the robot emoji from Twemoji by Twitter, licensed under CC-BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Source: https://github.com/twitter/twemoji

During the countdown and the chase the page asks the phone to keep its screen on (the Screen Wake Lock API), so a short auto-lock does not hide the tab mid-round. It lets go when the result shows or the player leaves, and asks again if the tab comes back into view. The timer sits at the top of the lobby screen in large type, yellow during “Get ready” and red for the last 10 seconds. The player list is a scoreboard: a seat badge, the name, a pull bar scaled to the strongest pull, and the shake count, with the robot’s target marked. The result is personal: “You won!” or “You tied!” in green on the winners’ phones, otherwise who won, with a line saying whether the robot reached them or they were closest when time ran out. Android phones also buzz for the winners. Once a player is in a lobby the “Connected” and “Shaking is on” lines are hidden; the status comes back if the connection drops. On a rematch’s last-match map, the mark line says “Your mark appears when the game starts” instead of pointing at a mark from the old layout.

Each counted shake makes the shake counter pop, and Android phones give a 15 ms buzz. During the chase a dashed red line runs from the robot to its target, with a pulsing ring around the target’s mark that holds still when the phone asks for reduced motion. The countdown is a large yellow 3, 2, 1 with a beep each second, then a green “GO!” with a higher tone when shakes start counting. The last 3 seconds tick, and the result plays a high tone for winners and a low one for everyone else. Browsers only allow sound after a tap, so the first tap on the page unlocks it.

While a lobby is open to joins, every phone shows a QR code and a “Share invite link” button. The link is the lobby address with `?code=` and the lobby code, and opening it fills in the code on the join screen. The server draws the QR code at `/qr.svg` with the `segno` package, and only for http or https links of at most 200 characters. Invites use the public address from `ngrok.yml` when there is one, so a host who opened the page on the laptop still hands out a link phones can open. Phones that are not in the lobby see its code too. The server sends them an `open_lobby` message when they connect, when they leave a lobby, and whenever the open lobby’s code, size, or running state changes, but not on every score update. The page shows the code in large type above the join form, fills it into the code box unless the player typed a different one, and hides Create lobby, since a second lobby would be refused. While a game runs the banner says so, a rematch’s new code replaces the old one, and when the last player leaves the banner goes away and Create lobby comes back.

Every lobby message says whether the robot is online. Before the start, the creator sees “Robot ready. Put it on the center mark, facing seat 0, then start.” or, in red, “Robot offline. The round will run, but the robot won’t move.” During a chase with the robot offline, the chase line reads “Robot offline, so it isn’t moving”. The main actions (Enable shaking, Create, Join, Start, Rematch) are yellow buttons, and Leave and Share are quieter outlined ones.

When the round ends, the page shows the winner and whether the robot got there or the clock ran out. A quiet round says draw. The chase line stays on the frozen pull from the end of the round. The leave button is hidden while the 45 seconds are running.

### Phone edge cases

- A phone that loses the connection shows “reconnecting” and returns to the join screen. It cannot upload shakes from the gap.
- Leaving, or closing the page, removes that player from the lobby immediately.

## Game server

The game server is the source of truth for lobbies, seats, the clock, shake scores, pull, the chase target, the pose, and the winner. It runs on the laptop and speaks to phones over a WebSocket. It can open the serial port. While a round is open, `server/chase.py` keeps a pose and sends the planner’s chunks through the bridge.

### Room creation

Any player who has enabled shaking can create a lobby from their phone. Only one lobby can exist at a time, because there is one robot.

- The server generates a room code. A second create is refused while that lobby still has someone in it. If the round has not started, the message includes the code to join. If a game is underway or the result is still up, the message says a game is already running.
- Rematch replaces that lobby. It does not open a second one.
- The creator is the first player. The lobby stores the player list and whether the round has started.
- When the last player leaves, the lobby is deleted and someone can create again.
- There is no idle-room timer and no separate host screen on the laptop.

### Joining

- A join requires a valid room code, a display name, and shaking enabled.
- The server accepts the join when the lobby has fewer than 8 players and the round has not started. A join after the start is rejected with “This game has already started.”
- Names are compared without regard to case. “Bea” and “bea” are the same name.
- There is no minimum other than the creator. The maximum is 8.
- Every join and leave is broadcast so every phone’s list matches.

### Start and the clock

The creator starts the round. Other players do not start it.

Start locks the seats and broadcasts a 3-second countdown, then a chase that ends 45 seconds after the countdown. Phones display both timestamps from the server. Shakes before the countdown finishes do not score, on the phone or on the server. The stored pose starts at home: `(0, 0)`, heading 0. The chase loop waits out the countdown before it sends a chunk.

Start also locks the seat list. Seat `i` of `N` players receives the angle `i × 360° / N`. People can still leave during the lobby, so the count is the number of players present at start. Before that, the page draws the same spacing from whoever is in the lobby, and those marks move when the roster changes. The robot is drawn at the center until the chase moves it. A rematch keeps the previous result on the arena until the next start.

### Shake score

The score is the number of shakes accepted during the round. It does not fade.

- The phone sends a running total. The server adds the increase since the last total it accepted from that player.
- An increase is stored only while the round is open, the total went up, and the jump is at most 12. A larger jump is dropped.
- Totals that arrive up to about half a second after the end timestamp still count, so the last shake sent before zero is included. After that grace, the round is finished and further totals do not score.
- The scoreboard is broadcast with each accepted change.
- The shake count is shown on the phone. It does not pick the winner. Arrival or the chased player does, as described under Pull.

### Pull and the chase target

Pull is a decaying score on top of the shake count. It is who the robot follows. When the Arduino is offline, the target is only a line on the phone and the robot stays still.

- Each accepted shake adds that same increase to the player’s pull. A dropped jump adds nothing.
- About four times a second the server fades every player’s pull. The half-life is 2.5 seconds. Pull below 0.05 becomes zero.
- The chase target is the player with the highest pull, as long as that pull is above zero. If two players have the same pull, the lower seat wins the comparison.
- The target switches only when a challenger leads by at least 1 pull, or by 15% of the current target’s pull, whichever is larger. A tie, or a lead inside that margin, keeps the current target.
- If every pull is zero, there is no target. The phone says the robot is holding still.
- If the chased player leaves and someone else still has pull, the next leader becomes the target. Their seat number does not change.
- Pull fades only while the round is open, including the half-second grace. When the round finishes, pull freezes at the value it had at the end of that grace.
- The scoreboard is broadcast when pull changes the list, including a change of target.

### Disconnects

A WebSocket close removes the player immediately. There is no reconnect grace and no reserved seat. If the creator leaves and the lobby is not empty, the next player becomes the creator. If they leave during a finished round, the result remains for whoever is still there.

### Server state

Each lobby moves through this sequence:

1. **Lobby** — players join and leave. Shakes do not score.
2. **Playing** — the 45-second window is open, shakes score, pull fades, the chase sends chunks, and the leave button is hidden. A chunk already on the motors is allowed to finish after the clock, and the round stays open until that `DONE` is applied.
3. **Result** — the shake-count winner is fixed, shakes no longer score, pull stays where it froze, and players can leave.
4. **Rematch** — the creator reopens the finished lobby under a new code with the same players and fresh scores. It is back in the Lobby state, so new players can join.
5. The lobby ends when the last player leaves.

## Later: robot motion

Seats, floor marks, fading pull, the chase line, the pose, and the chunk loop are in the running server. A round calls `server/pose.py` and `server/planner.py`, sends one chunk through the bridge, and ends on arrival or on the clock. A disconnect still removes the player immediately.

Between rounds the host puts the robot back on the center mark, pointed at seat 0. The server does not drive it home and does not keep a seat across a disconnect.

## Physical model the software depends on

The robot cannot see the phones. Indoor GPS and phone compass headings are too coarse to aim a small robot at a person. Each player claims a numbered mark on the floor, and that mark is their location for the whole game.

Marks sit on a circle around the robot’s home point, evenly spaced. The robot starts each round at the center, pointed at seat 0. Seat `i` of `N` players is the angle `i × 360° / N`. The mark coordinates are:

```text
mark(i) = (R cos θ, R sin θ)
θ = i × 360° / N
```

The arena is a square of 1 foot on each side, 304.8 mm. Home is the center. `R` is 152.4 mm, the circle that fits inside that square and touches the middle of each side. Every mark stays inside the square. Heading 0 points along +x, toward seat 0. Positive heading turns toward higher seat numbers. On the wire, `DRIVE` direction `1` moves the car away from seat 0, so a drive along heading 0 is sent as direction `-1`. `SPIN` direction `1` turns from seat 0 toward seat 1, which is the positive heading. `SPIN` direction `-1` turns toward lower seat numbers.

`server/pose.py` stores the robot’s pose: `x` and `y` in millimeters, heading in degrees, and whether that pose is known. Home is `(0, 0)`, heading 0, known. Every finished spin updates the heading. Every finished drive updates `x` and `y` along the heading it had when the drive started. `STOP`, a timeout, or a dropped cable marks the pose unknown, and a later `DONE` is ignored until home is confirmed. Confirming home sets `(0, 0)`, heading 0, known. The pose is only trustworthy if the round begins on the home pose and every chunk runs to completion. Each round starts a fresh pose at home.

Players stand on their marks and stay there. The arrival radius in `server/planner.py` is 25 mm, a starting value smaller than the distance from the mark to the player’s feet, so the robot can “reach” someone and stop short of them. Home is 152.4 mm from every mark, so the center does not count as an arrival.

The scale constants below are the theoretical guesses, not a measured calibration. The powered wheels are 38 mm across. One wheel revolution is 4096 half-steps, so straight travel is `4096 / (π × 38)` steps per millimeter, about 34.31. `server/pose.py` and `server/planner.py` use 34.31. One half-step is about 0.0291 mm. The center-to-mark drive is 152.4 mm, about 5229 half-steps, about 16 seconds at 3 ms per step.

The wheelbase `b` is 5 inches, 127 mm, measured between the centers of the two powered tires. With the wheels turning opposite ways, steps per degree is `127 × 4096 / (38 × 360)`, about 38.03. The same modules use 38.03. A full turn in place is about 13689 half-steps.

Open-loop steppers drift if the robot is bumped or a move is cut off. Between games the host sets the robot back on the center mark by hand, pointed at seat 0. The next round stores a fresh pose at `(0, 0)`, heading 0.

## How a chase round feels

The running round counts down for 3 seconds, chases for 45 seconds, draws the arena, and ends on arrival or on the clock. The host places the robot on the center mark before the round.

1. Players join, get a seat, and stand on that mark. The robot sits at the center, pointed at seat 0.
2. The host starts. A short countdown plays. Shakes during the countdown do not count.
3. The shake window opens and the robot starts moving. Each phone’s shakes add pull. Pull fades if that person stops, so the robot follows current effort.
4. The planner picks the player with the strongest pull and sends a short spin or a short drive toward that player’s mark. When the chunk finishes, it looks at the scores again and sends the next chunk.
5. If someone overtakes the leader, the next chunk aims at the new leader. The robot visibly changes direction in the middle of the round.
6. The round ends in one of two ways. The robot’s pose comes within the arrival radius of a mark, and that player wins. Or the clock runs out, and the player closest to the robot wins. Players at the same distance tie.
7. The result stays on screen. The next round starts from the center again.

While nobody has any pull, the robot holds still. The first shakes are what get it moving.

## Chase phone client

A mobile web page, served by the laptop, for the robot game. The running page shows the seat, the mark, the pull, who is being chased, and a drawing of the arena with the robot’s latest pose. A refresh does not resume the same seat.

The page has four jobs: join a room, show which floor mark to stand on, count shakes, and show the live chase.

### Join a room

The landing screen asks for a room code and a display name.

- The room code is short enough to read aloud.
- The display name is what the scoreboard shows. The server assigns the seat number. Players choose a name.
- Empty names, duplicate names in the same room, and a full room (8 players) get a clear message on the page.
- After a successful join, the page stores the player id for the tab session so a refresh can try to resume the same seat. Closing the tab drops the player after the server’s disconnect timeout.
- The page shows the connection state: connecting, in the lobby, in a round, reconnecting, and removed.

### Seat assignment

The server assigns the next free seat when the player joins. The page shows that seat in large type (“You are seat 3”) and tells the player to stand on the matching floor mark. The lobby list shows every joined name and seat so people can sort out who is standing where before the host starts.

Seats stay fixed for the life of the room. A player who drops and rejoins with the same session can reclaim the same seat while it is still reserved. A brand-new join gets a new free seat.

### Motion permission

Shake detection uses the phone’s accelerometer through the browser motion events.

- iOS only exposes motion data on an HTTPS page, and only after a tap that calls the permission request. The laptop must serve the page with a certificate, including on a local address.
- Android is more permissive. The same page still asks everyone to tap an “Enable shaking” button so both platforms share one flow.
- Until permission is granted, the player can sit in the lobby and cannot add pull. The host sees that player as not ready to score.
- If the browser has no motion API, the page says this phone cannot play, and the server does not count that player toward the minimum.

### Shake detection

The phone counts shakes locally and sends the running total for this round to the server a few times a second. It sends a total, not a claim that it is winning.

A shake counts when the acceleration magnitude crosses a fixed threshold and then falls back below it. One continuous rattle is one count. The threshold and the settle time are constants tuned on real phones. The page shows the player’s own shake count so they can feel the phone registering hits.

The phone sends counts only while the server says the round is open. Shakes before the start and after the round ends stay on the phone and are discarded. If the tab is hidden or the page is backgrounded, counting pauses and the last total stays in place.

### Live chase

During the round the page shows every player’s name, seat, and current pull, ordered by pull. Pull is the number the robot is listening to. The local player’s row is marked. The row of the player being chased is marked separately, with a line such as “The robot is coming for you” on that player’s own phone.

A countdown shows the time left, using the server’s end timestamp so phones with drifting clocks still agree. The page also shows a simple arena: marks around a circle and the robot’s latest pose, so people who cannot see the table still understand why it turned.

When the server ends the round, the page switches to the result: winner name and seat, whether they won by arrival or by the clock, and the final pull values. The next round returns the page to the lobby or to a “get ready” state, depending on what the server broadcasts.

### Phone edge cases

- A phone that loses Wi-Fi shows “reconnecting” and then returns to the join screen. The seat is gone. There is no reserved seat to resume.
- A phone that was disconnected cannot upload a burst of shakes from while it was offline. Pull only moves when the server accepts a new total.
- Two tabs with the same player id follow the server’s rule: the latest connection owns the seat, and the older tab is told it was replaced.

## Chase game server

The running server is the source of truth for rooms, seats, the countdown, the 45-second clock, shake scores, pull, the chase target, and the pose. It opens the serial port, sends the planner’s chunks, and ends the round on arrival or on the clock. A dropped phone loses its seat. The host places the robot on the center mark by hand before the next round.

### Room creation

A host creates a room from the laptop, or from a phone that then becomes the host.

- The server generates a room code that is unique among rooms that are still open.
- The room records a host id, the player list, the round state, and the robot pose. A new game sets the pose to home: `(0, 0)`, heading 0°.
- One lobby is open at a time. A second create is refused until that lobby is empty. Rematch replaces it.
- Closing the host does not have to delete the room immediately. An idle room expires after a timeout so codes get reused.

### Joining and seats

- A join requires a valid room code and a display name.
- The server accepts the join when the room has fewer than 8 players and the room is still in the lobby. A join during a round is rejected with “round in progress.”
- Seats are integers from 0 to N−1 in join order. The angle for seat `i` is `i × 360° / N` using the number of players present when the host starts the round. People can still leave during the lobby, so angles are computed at start, not at join. The circle then matches the people actually playing.
- The minimum to start is 2 players. The maximum is 8.
- Every join, leave, and rename is broadcast to the room so every phone’s lobby list matches.

### Ready and start

The host starts the round. Other players do not start it.

Before the start is accepted:

- At least 2 players are connected.
- The host has placed the robot on the center mark, pointed at seat 0. The server stores that as home when the round starts.
- The robot can be offline. The chase then holds still and the phones still play.
- The lobby shows who has not enabled shaking. Those players can still be in the round and will sit at zero pull until they enable it.

Start locks the seat list, computes mark positions, broadcasts a countdown, then a round-open message with the round end timestamp. Phones display that timestamp. The server is the clock that ends the round.

The round length is a server constant on the order of 45–60 seconds. The motors need several seconds to turn and cross the circle, and the fun of the demo is a lead change while the robot is already moving. Arrival can end the round sooner.

### Pull

Pull is a decaying score, not a lifetime shake count. A lifetime total would let an early leader own the robot for the rest of the round. Decay means the robot follows whoever is shaking now.

- Each accepted shake adds 1 pull to that player.
- On a fixed server tick, every player’s pull is multiplied by a decay factor. A half-life of about 2–3 seconds is the starting point: stop shaking and, a few seconds later, someone who is still going takes the robot.
- The phone still sends a monotonic shake total for the round. The server treats the increase since the last accepted total as the new shakes. The phone does not compute decay.
- An increase is stored only while the round is open, the total went up, and the jump fits under a physical rate limit. A jump larger than that limit is dropped.
- Pull is broadcast with the scoreboard so every phone shows the same race.
- The chase target is the player with the highest pull, as long as that pull is above zero.
- The target switches only when a challenger leads by a set margin (a fraction of the current pull, or a small absolute lead). A tie, or a lead inside the margin, keeps the current target. That stops the robot from twitching when two people are nearly even.
- If every pull is zero, there is no target and the planner sends nothing.

The rate limit exists so a modified client cannot jump from 0 to a huge pull in one message. Honest phones send small increases several times a second, so the limit sits just above a fast human shake rate.

### Winner

The server ends the round on the first of these:

- **Arrival.** After a chunk, the planner reports that the pose is inside a player’s arrival radius. That player wins, even if they lost the pull lead on the same tick. The robot already got there.
- **Clock.** The end timestamp passes. The player closest to the robot wins. Players at the same distance tie, including when the robot is still at the center.
- **Dropped cable.** A move that loses the serial link is a draw, and the stored pose is marked unknown.

The result message includes the winner names, the reason (arrival, clock, or draw), and the final pull values. The room leaves Playing only after the current chunk has finished. The next round stores a fresh home pose after the host places the robot on the center mark.

### Disconnects

- A WebSocket close removes that player immediately. The seat is not reserved.
- During the lobby, later seats pack down. During a round, the seat number stays and that player’s pull stops growing.
- If the creator leaves and someone remains, the next player becomes the creator. A finished round keeps its result for whoever is still connected.

### Server state

Each room moves through a single sequence:

1. **Lobby** — players join and leave. The robot is idle at home.
2. **Countdown** — seats are locked, no more joins, shakes are not counted yet. The robot stays still.
3. **Playing** — pull is accepted, the planner sends chunks, phones show the chase. This state owns both the scoreboard and the motors.
4. **Result** — the robot is idle, the winner is fixed, and the pose is wherever the robot stopped.
5. **Next round** — the host places the robot on the center mark by hand. The next start stores heading and position as home again.

There is no separate “drive after the scores freeze” phase. Motion is part of Playing.

## Motion planner

`server/planner.py` chooses one chunk. It does not open the serial port, read shakes, or compute pull. The caller hands it a pose, a target mark, and the list of marks. `server/test_planner.py` covers that choice with no Arduino attached.

`server/chase.py` is the Playing loop. Each finished chunk updates the pose, tells the phones, and calls the planner again. The planner does not interrupt a chunk that is already on the motors. A lead change shows up on the next call. The loop waits out the 3-second countdown before the first chunk.

### Pose update

`server/pose.py` applies a finished reply. Heading stays in a single 0–360 range. Radians are used only inside sine and cosine.

When `DONE SPIN` arrives for `steps` at `direction`:

```text
heading = wrap(heading + direction × steps / 38.03)
```

When `DONE DRIVE` arrives for `steps` at `direction`, the heading is the one from before that drive:

```text
distance = -direction × steps / 34.31
x = x + cos(heading) × distance
y = y + sin(heading) × distance
```

Direction `-1` travels along the heading. At heading 0 that increases `x` and leaves `y` at 0. Direction `1` travels the opposite way. Spin changes heading only.

`STOP`, a timeout, or a dropped cable marks the pose unknown without inventing a new position. A later `DONE` does not move it. Confirming home sets `(0, 0)`, heading 0, known.

### Next chunk

`mark_at` places a mark on the 152.4 mm circle. Angle 0 is seat 0, at `(152.4, 0)`.

Let the target mark be `(tx, ty)`, and let the bearing from the robot to that mark be `bearing`. The heading error is the shortest signed angle from the current heading to `bearing`, from −180° through 180°.

`plan` checks every supplied mark, then chooses at most one chunk:

- If the pose is unknown, send nothing and do not report an arrival.
- If there is no target, send nothing.
- If any mark is within 25 mm, report that mark’s index and send nothing. The closest mark wins. An equal distance keeps the earlier mark.
- If the absolute heading error is under 90°, face the mark. While that error is above 15°, send `SPIN` for the smaller of the error and 5°, in the direction of the error. Once it is within 15°, send `DRIVE` forward along the heading, direction `-1`.
- If the absolute heading error is 90° or more, point the tail at the mark and reverse. The spin is the shorter turn onto that reverse line, still capped at 5°. An error of 180° is already on that line, so the chunk is a reverse `DRIVE`, direction `1`, with no spin. Within 15° of the reverse line, the drive is direction `1`.

A 5° spin is 190 steps, about 0.6 seconds at 3 ms per step. A full 30 mm drive is 1029 steps, about 3 seconds. A shorter remainder is not padded out to 30 mm. These chunk sizes, the 15° band, the 90° reverse choice, and the 25 mm arrival radius are starting values at the top of `server/planner.py`, to be tuned on the chassis. An error of exactly 15° drives forward. An error of exactly 90° lines up to reverse.

### Arrival and the clock

Arrival across every mark is in `plan`. That covers a short drive that enters a mark just as the lead changes. `server/chase.py` ends the round on that report and names that player, even if the clock has also run out.

The clock rule is not in the planner. When a chase round exists, the server lets the chunk already in flight finish, then stops. It does not start another move. The server names the player closest to the stored pose as the clock winner. Players at the same distance tie.

### Between rounds

The host places the robot on the center mark, pointed at seat 0, before the next lobby starts. The server does not drive it home. Each new round stores the pose as `(0, 0)`, heading 0, which matches that placement.

### Planner outcomes

- **Chunk completed.** The caller applies the `DONE` line to the pose, then calls `plan` again. The module returns the next chunk, an arrived mark, or nothing when there is no target. The clock check is still the server’s job.
- **No target.** `plan` returns no chunk. The pose stays put.
- **Serial failure or timeout.** The planner module does not handle the port. The chase round would stop as a draw, tell the phones the drive failed, and call `mark_unknown` until the host confirms home.
- **Host stop.** The bridge sends `STOP`. Applying `STOP` to the pose marks it unknown until home is confirmed.

The planner never reads accelerometers and never computes pull. The server hands it a target, or no target.

## Serial bridge

`server/bridge.py` is the only code that opens the Arduino port. It uses pyserial. One thread reads and writes that port, so a wait cannot freeze the phone server. `server/chase.py` hands the bridge one chunk at a time and waits for completion before the next, so a drive cannot start on top of a spin.

### Port

- The port name is the `RATTLE_PORT` environment variable, such as `COM5`. Auto-detect is optional later.
- The bridge opens that port when the game server starts and keeps it open. Opening the port usually resets the Arduino. The bridge waits up to 2 seconds for `READY`, then sends `PING`. `PONG` is what marks the link up.
- If `RATTLE_PORT` is unset, or the port is missing, or the board does not answer, the server logs that the robot is offline and the lobby still runs. Start is not rejected. The phone does not show a robot status yet. Rejecting start while the robot is offline belongs with the later chase round.
- A timeout, a dead cable, or a reply that does not match closes the port and leaves the bridge offline. It does not reconnect by itself. The chase marks the pose unknown and ends the round as a draw. The page says draw. The next round starts a new pose at home.

### Messages

Lines of text, one command or one reply per line. Human-readable text is enough at this baud rate and makes a serial monitor usable while tuning.

Commands the bridge sends:

| Command | Meaning |
|---|---|
| `SPIN <steps> <direction>` | Move `<steps>` half-steps with the motors in opposite directions. `<direction>` is `1` or `-1`. |
| `DRIVE <steps> <direction>` | Move `<steps>` half-steps with both motors in `<direction>`. |
| `STOP` | Release both coil sets immediately and cancel the current move. |
| `PING` | Ask the board to prove the link is up. |

Replies the firmware sends:

| Reply | Meaning |
|---|---|
| `READY` | Sent once from `setup` after the pins are safe. |
| `PONG` | Answer to `PING`. |
| `DONE SPIN <steps> <direction>` | The spin finished. The counts match the command so the planner can update heading. |
| `DONE DRIVE <steps> <direction>` | The drive finished. The counts match the command so the planner can update `x` and `y`. |
| `DONE STOP` | A stop finished with the coils released. Steps completed are not reported. Pose is unknown afterward. |
| `ERR BUSY` | A motion command arrived while a move was still running. |
| `ERR BAD` | The line could not be parsed. |

`<steps>` is an integer from 1 through 16000. `<direction>` is only `1` or `-1`. The bridge refuses to send anything else. A second spin or drive, while one is already on the port, is refused and is not written.

During Playing the bridge sends `STOP` only for a host abort or a serial recovery. Lead changes do not use `STOP`. The current chunk is allowed to finish so the pose math still matches the wheels.

### Waiting and timeouts

The bridge writes one command and reads until the matching `DONE` line, or until a timeout. A move may take the step count times 3 ms, plus 1 second. `PING` and `STOP` wait up to 1 second. `READY` and a stray `PONG` while a move is running are logged and skipped.

`ERR BUSY` and `ERR BAD` fail that motion. The bridge does not retry a motion on its own. A retry could repeat steps the wheels already took. The planner records the failure, the server ends the round, and the host recovers by homing.

`STOP` is the exception the host can send while a chunk is running. The firmware aborts the step loop, releases the coils, and replies `DONE STOP`.

### What the bridge does not do

The bridge does not compute angles, store pull, or choose motor pins. A spin of 40 steps at direction `-1` is opaque to it. That keeps serial failures independent of the chase.

## Firmware

`firmware/dual_motor` is the game sketch. `firmware/drive_test` and `firmware/spin_test` are the two-motor bench sketches: same direction rolls, opposite directions turn in place. `firmware/motor_test` and `firmware/stepper_driver` stay as single-motor tests. The game sketch keeps the existing motor model:

- The same 8-phase half-step sequence.
- Motor 1 on pins 4–7, motor 2 on pins A0–A3.
- Each motor keeps its own phase index so a spin does not corrupt the other motor’s phase.
- Each step writes both motors, then waits the step delay once.
- Coils are released when a chunk ends, so the motors do not sit powered between chunks. The next chunk starts immediately, so the release is brief. The phase index is kept across that release.

### Command executor

`setup` configures both motors, releases the coils, opens serial, and prints `READY`.

`loop` reads one line when no move is running. A parsed `SPIN` or `DRIVE` runs to completion, then prints `DONE` with the same step count and direction it executed. The step loop checks for a `STOP` line between steps so the host can abort a chunk.

Behavior of each command:

- **SPIN.** For each step, advance motor 1 by `direction` and motor 2 by the opposite direction, then wait the step delay. Direction `1` turns from seat 0 toward seat 1. Direction `-1` turns toward lower seat numbers.
- **DRIVE.** For each step, advance both motors by `direction`, then wait the step delay. Direction `1` rolls away from seat 0. Direction `-1` rolls toward seat 0.
- **STOP.** Break out of the current step loop, release both coil sets, and print `DONE STOP`.
- **PING.** Print `PONG` when idle. During a move, a ping can wait. Stop takes priority over ping.

Malformed lines print `ERR BAD` and leave the motors released.

### Motion details that stay on the board

- Step delay stays a firmware constant. The laptop does not stream individual coil phases.
- Phase indices persist across commands so the next chunk continues from the electrical phase where the last chunk stopped. Releasing the coils does not reset the index. Resetting it would make the next step jump.
- Bounds: a step count outside 1 through 16000 is `ERR BAD`, so a bad serial line cannot spin forever. 16000 half-steps is a few wheel revolutions, enough to cross the arena.
- Baud rate is 115200, shared with the serial bridge.

### What stays off the board

The sketch does not know player names, seats, pull, or the round timer. It cannot decide who is being chased. Each command is one short spin or one short drive. The laptop is what strings those chunks into a chase.

## Shared rules

### Shakes and pull, as the game works now

- A shake is motion at or above a threshold of about 15 m/s², including gravity. While the phone stays that strong, another shake counts about every 150 ms.
- The phone sends its running total for the open round when the count increases.
- The server adds the increase only while the round is open, including a short grace after zero, and only when the jump is at most 12. That increase is added to both the shake count and the pull.
- Pull halves every 2.5 seconds and drops to zero below 0.05. The chase target switches only when a challenger leads by at least 1 pull or 15% of the current pull.
- Zero pull means the phone says the robot is holding still, and the chase sends nothing.
- Reaching a mark wins, and the page says the robot got there. If the clock runs out first, the closest player wins and the page says they were closest when time ran out. Players at the same distance tie. Pull freezes with the result.
- Shakes while the tab is hidden are not counted.
- Shakes before the start and after the countdown reaches zero are not sent.
- Leaving the lobby resets the phone’s count. A disconnect cannot fill in shakes from the gap.
- Shaking must be enabled before a player can create or join a lobby.

### Shakes and pull, for the later robot chase

- A shake for that chase is a threshold crossing followed by a settle, so one continuous rattle is one count.
- Pull decays on a server tick with a half-life of a few seconds, and the robot follows the pull leader.
- The chase target switches only when a challenger leads by a margin.
- Zero pull means the robot holds still.

### Pose and motion

`server/pose.py`, `server/planner.py`, and `server/chase.py` implement these rules:

- Home is `(0, 0)`, heading 0°, pointed at seat 0. Every round starts there. The host places the robot on that mark by hand.
- Mark positions are computed from the player count at round start and do not change mid-round.
- Inside 90° the robot turns to face the live target, then drives forward. At 90° or more it turns until the tail points at the target, then reverses.
- Both motors step on the same tick. Opposite directions spin. Matching directions drive.
- Pose updates only from a `DONE` line for a chunk that finished every step.
- `STOP`, a serial timeout, or a disconnect marks the pose unknown. The next round stores a fresh home pose after the host places the robot by hand.
- Coils are off whenever the firmware is idle.
- The in-flight chunk finishes when the leader changes. The chunk after that aims at the new leader.

## Connection, hosting, and phone limits

- The laptop runs the web server and the WebSocket server on port 8080. ngrok forwards a public HTTPS address to that port. Phones open the ngrok address.
- Each player taps once to enable shaking before the lobby controls appear.
- A lobby holds up to 8 players. Join is refused above 8 and after the start. The creator can start alone.
- Set `RATTLE_PORT` to open the Arduino when the server starts. A round then sends one chunk at a time. Motor power comes from the external 5V supply, with grounds tied to the Arduino.

## Suggested build order

The phone game below is in place, including the chase loop. The car rolls and can be told to turn in place from the bench sketches. A round sends those moves when the robot is online.

Done:

1. **Connection.** The laptop serves the page and a WebSocket. Phones reach it through ngrok.
2. **Lobby.** Create a room, join from other phones, refuse a ninth player, and require shaking first.
3. **Shake score.** Permission, counting on the phone, totals into the server, and a clock on the server.
4. **Seats.** Assign a seat and a floor mark, pack seats until the start, then lock the angles.
5. **Fading pull.** Turn accepted shakes into a score that drops when someone stops, and show who the robot would chase.
6. **Firmware commands.** `firmware/dual_motor` runs `SPIN`, `DRIVE`, `STOP`, and `PING`, and the `DONE` reply echoes the step count and direction.
7. **Serial bridge.** `server/bridge.py` opens `RATTLE_PORT`, sends one command, and waits for `DONE` or a timeout.
8. **Pose.** `server/pose.py` updates `x`, `y`, and heading from a finished `SPIN` or `DRIVE`, using 34.31 steps per millimeter and 38.03 steps per degree. Direction `-1` travels along the heading. `STOP` marks the pose unknown. The next round stores a fresh home pose.
9. **Planner.** `server/planner.py` aims one short chunk at a mark on the 152.4 mm circle. Inside 90° it spins at most 5° toward the mark, then drives forward at most 30 mm with direction `-1`. At 90° or more it lines up the tail and reverses with direction `1`. A mark within 25 mm is reported and no chunk is sent.
10. **Chase round.** `server/chase.py` hands the live target and the pose to the planner, sends the chunk through `server/bridge.py`, updates the pose from `DONE`, and ends the round on arrival or when the clock expires. The round is 45 seconds. A dropped cable during a move is a draw.
11. **Countdown and arena.** A 3-second countdown blocks shakes and motion so the host cannot start early. The phone draws the marks and the robot from the pose in each server message. Between rounds the host places the robot on the center mark by hand.
