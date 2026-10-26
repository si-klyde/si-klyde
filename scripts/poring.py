#!/usr/bin/env python3
"""Render the contribution graph as an animated SVG: a Poring hops over it and eats every active day."""

import json
import os
import sys
import urllib.request
from pathlib import Path

USER = os.environ.get("GH_USER", "si-klyde")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")

CELL, GAP = 11, 3
PITCH = CELL + GAP
PAD_X, PAD_TOP, PAD_BOTTOM = 24, 46, 30
HOP = 0.16  # seconds per hop
PAUSE = 2.5  # seconds with an empty graph before the loop restarts

THEMES = {
    "light": {
        "bg": "#ffffff",
        "levels": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
        "text": "#57606a",
    },
    "dark": {
        "bg": "#0d1117",
        "levels": ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"],
        "text": "#8b949e",
    },
}
LEVEL = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { weekday contributionCount contributionLevel } }
      }
    }
  }
}
"""

# Poring drawn around (0, 0) = bottom centre, ~18px wide.
PORING = """
<ellipse cx="0" cy="1" rx="8" ry="1.6" fill="#000" opacity=".18"/>
<path d="M-9 0 C-10 -7 -5 -13 0 -14 C1 -16 3 -17 4 -16.5 C2 -15.5 2 -14.5 3 -13.5 C7 -12 10 -6 9 0 Z"
      fill="#ff9ec4" stroke="#c84f82" stroke-width="1"/>
<ellipse cx="-3.5" cy="-10" rx="2.4" ry="1.4" fill="#fff" opacity=".75" transform="rotate(-30 -3.5 -10)"/>
<ellipse cx="-2.6" cy="-6" rx=".9" ry="1.5" fill="#2b1a22"/>
<ellipse cx="2.6" cy="-6" rx=".9" ry="1.5" fill="#2b1a22"/>
<path d="M-1.6 -3.2 Q0 -1.4 1.6 -3.2 Z" fill="#c84f82"/>
<ellipse cx="-5.2" cy="-3.8" rx="1.3" ry=".7" fill="#ff6fa3" opacity=".6"/>
<ellipse cx="5.2" cy="-3.8" rx="1.3" ry=".7" fill="#ff6fa3" opacity=".6"/>
"""


def fetch_calendar():
    token = os.environ["GITHUB_TOKEN"]
    body = json.dumps({"query": QUERY, "variables": {"login": USER}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        data = json.load(resp)
    if "errors" in data:
        sys.exit(f"GraphQL error: {data['errors']}")
    return data["data"]["user"]["contributionsCollection"]["contributionCalendar"]


def build_cells(calendar):
    cells = []
    for x, week in enumerate(calendar["weeks"]):
        for day in week["contributionDays"]:
            cells.append({"x": x, "y": day["weekday"], "level": LEVEL[day["contributionLevel"]]})
    return cells


def hop_path(cells):
    """Active cells in serpentine column order so hops stay short."""
    active = [c for c in cells if c["level"] > 0]
    active.sort(key=lambda c: (c["x"], c["y"] if c["x"] % 2 == 0 else -c["y"]))
    return active


def cell_center(c):
    """Where the Poring stands: bottom centre of the cell."""
    return PAD_X + c["x"] * PITCH + CELL / 2, PAD_TOP + c["y"] * PITCH + CELL


def pct(t, total):
    return f"{100 * t / total:.3f}%"


def poring_keyframes(points, total):
    """Position keyframes: rise with ease-out, fall with ease-in for a parabolic arc."""
    frames = []
    for i in range(len(points) - 1):
        (x0, y0), (x1, y1) = points[i], points[i + 1]
        lift = 10 + min(abs(x1 - x0) + abs(y1 - y0), 60) * 0.3
        t0, tm = i * HOP, i * HOP + HOP / 2
        frames.append(f"{pct(t0, total)}{{transform:translate({x0:.1f}px,{y0:.1f}px);animation-timing-function:ease-out}}")
        frames.append(
            f"{pct(tm, total)}{{transform:translate({(x0 + x1) / 2:.1f}px,{min(y0, y1) - lift:.1f}px);animation-timing-function:ease-in}}"
        )
    x, y = points[-1]
    frames.append(f"{pct((len(points) - 1) * HOP, total)},100%{{transform:translate({x:.1f}px,{y:.1f}px)}}")
    return "@keyframes hop{" + "".join(frames) + "}"


def squish_keyframes(hops, total):
    """Squash on landing, stretch on take-off."""
    frames = ["0%{transform:scale(1,1)}"]
    for i in range(1, hops + 1):
        land = i * HOP
        frames.append(f"{pct(land - 0.01, total)}{{transform:scale(.9,1.12)}}")
        frames.append(f"{pct(land, total)}{{transform:scale(1.25,.75)}}")
        frames.append(f"{pct(land + 0.05, total)}{{transform:scale(1,1)}}")
    frames.append("100%{transform:scale(1,1)}")
    return "@keyframes squish{" + "".join(frames) + "}"


def render(calendar, theme):
    t = THEMES[theme]
    cells = build_cells(calendar)
    path = hop_path(cells)
    weeks = len(calendar["weeks"])
    width = PAD_X * 2 + weeks * PITCH - GAP
    height = PAD_TOP + 7 * PITCH - GAP + PAD_BOTTOM

    # Off-grid entry and exit so the Poring hops in from the left and out to the right.
    first_y = cell_center(path[0])[1] if path else PAD_TOP + 3 * PITCH
    last_y = cell_center(path[-1])[1] if path else first_y
    points = [(-12, first_y)] + [cell_center(c) for c in path] + [(width + 12, last_y)]
    hops = len(points) - 1
    total = hops * HOP + PAUSE

    eaten_at = {id(c): (i + 1) * HOP for i, c in enumerate(path)}
    empty = t["levels"][0]
    css, rects = [], []
    for i, c in enumerate(cells):
        x, y = PAD_X + c["x"] * PITCH, PAD_TOP + c["y"] * PITCH
        fill = t["levels"][c["level"]]
        cls = ""
        if id(c) in eaten_at:
            cls = f' class="c{i}"'
            p = pct(eaten_at[id(c)], total)
            css.append(
                f"@keyframes e{i}{{0%,{p}{{fill:{fill}}}{p},96%{{fill:{empty}}}100%{{fill:{fill}}}}}"
                f".c{i}{{animation:e{i} {total:.2f}s step-end infinite}}"
            )
        rects.append(f'<rect{cls} x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" fill="{fill}"/>')

    css.append(poring_keyframes(points, total))
    css.append(squish_keyframes(hops, total))
    css.append(f".poring{{animation:hop {total:.2f}s linear infinite}}")
    css.append(f".body{{transform-origin:0 0;animation:squish {total:.2f}s linear infinite}}")

    label = f"{calendar['totalContributions']} contributions eaten in the last year"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<title>Poring eating {USER}'s contribution graph</title>
<style>{"".join(css)}</style>
<rect width="100%" height="100%" rx="6" fill="{t["bg"]}"/>
{"".join(rects)}
<text x="{PAD_X}" y="{height - 10}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace" font-size="11" fill="{t["text"]}">{label}</text>
<g class="poring"><g class="body"><g transform="scale(1.35)">{PORING}</g></g></g>
</svg>
"""


def main():
    calendar = fetch_calendar()
    OUT.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        (OUT / f"poring-{theme}.svg").write_text(render(calendar, theme))
    print(f"wrote {OUT}/poring-{{light,dark}}.svg")


if __name__ == "__main__":
    main()
