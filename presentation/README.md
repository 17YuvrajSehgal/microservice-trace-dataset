# presentation

Standalone slide decks. No server, no build, no network — open the file in a browser.

| file | what |
|---|---|
| `how-it-works.html` | 15 slides: how the agent and blueprints work, ending on a handoff to the live demo |

## Presenting

Open `how-it-works.html` directly (double-click, or drag it into a browser).

| key | does |
|---|---|
| `→` / space / click | next slide |
| `←` | previous slide |
| `Home` / `End` | first / last slide |
| `F` | fullscreen |
| `T` | switch light and dark |

The slide number is in the bottom-right and in the URL hash, so you can reopen on a
given slide (`how-it-works.html#9`).

The last slide hands over to the live demo at `127.0.0.1:8765` — start it with
`python demo/app.py` before you present.

## On the numbers

Every number in the deck is measured, not illustrative: the 9.6 s / 133 s seek costs,
15 GB to 17 MB indexing, the agent's limits (4 subtasks / 18 turns / 2 rounds), and the
detection scoreboard all come from this repo's own runs.
