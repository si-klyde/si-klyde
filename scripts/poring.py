#!/usr/bin/env python3
"""Render the contribution graph as an animated SVG: a Poring walks over it and eats every active day."""

import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

USER = os.environ.get("GH_USER", "si-klyde")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")

CELL, GAP = 11, 3
PITCH = CELL + GAP
PAD_X, PAD_TOP, PAD_BOTTOM = 30, 36, 30
SPEED = 150  # px per second along the path
WALK = 0.7  # seconds per walk cycle
PAUSE = 2.5  # seconds with an empty graph before the loop restarts
ASSETS = Path(__file__).resolve().parent.parent / "assets"

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


def walk_path(cells):
    """Active cells in serpentine column order so steps stay short."""
    active = [c for c in cells if c["level"] > 0]
    active.sort(key=lambda c: (c["x"], c["y"] if c["x"] % 2 == 0 else -c["y"]))
    return active


def cell_center(c):
    """Where the Poring's feet go: just below the cell centre."""
    return PAD_X + c["x"] * PITCH + CELL / 2, PAD_TOP + c["y"] * PITCH + CELL * 0.8


def pct(t, total):
    return f"{100 * t / total:.3f}%"


def arrival_times(points):
    times, t = [0.0], 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        t += ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / SPEED
        times.append(t)
    return times


def walk_keyframes(points, times, total):
    frames = [f"{pct(t, total)}{{transform:translate({x:.1f}px,{y:.1f}px)}}" for (x, y), t in zip(points, times)]
    x, y = points[-1]
    frames.append(f"100%{{transform:translate({x:.1f}px,{y:.1f}px)}}")
    return "@keyframes walk{" + "".join(frames) + "}"


def poring_sprite():
    """Sprite strip from the game files: one row of walk frames, anchor = feet."""
    meta = json.loads((ASSETS / "poring-walk.json").read_text())
    png = base64.b64encode((ASSETS / "poring-walk.png").read_bytes()).decode()
    w, h, n = meta["width"], meta["height"], meta["frames"]
    ax, ay = meta["anchor"]
    css = (
        f"@keyframes cycle{{to{{transform:translateX(-{w * n}px)}}}}"
        f".frames{{animation:cycle {WALK}s steps({n}) infinite}}"
    )
    svg = (
        f'<ellipse cx="0" cy="0" rx="{w * 0.38:.1f}" ry="3.5" fill="#000" opacity=".2"/>'
        f'<svg x="{-ax}" y="{-ay}" width="{w}" height="{h}" viewBox="0 0 {w} {h}" overflow="hidden">'
        f'<image class="frames" width="{w * n}" height="{h}" style="image-rendering:pixelated" '
        f'href="data:image/png;base64,{png}"/></svg>'
    )
    return css, svg


def render(calendar, theme):
    t = THEMES[theme]
    cells = build_cells(calendar)
    path = walk_path(cells)
    weeks = len(calendar["weeks"])
    width = PAD_X * 2 + weeks * PITCH - GAP
    height = PAD_TOP + 7 * PITCH - GAP + PAD_BOTTOM

    # Off-grid entry and exit so the Poring walks in from the left and out to the right.
    first_y = cell_center(path[0])[1] if path else PAD_TOP + 3 * PITCH
    last_y = cell_center(path[-1])[1] if path else first_y
    points = [(-30, first_y)] + [cell_center(c) for c in path] + [(width + 30, last_y)]
    times = arrival_times(points)
    total = times[-1] + PAUSE

    eaten_at = {id(c): times[i + 1] for i, c in enumerate(path)}
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

    sprite_css, sprite = poring_sprite()
    css.append(sprite_css)
    css.append(walk_keyframes(points, times, total))
    css.append(f".poring{{animation:walk {total:.2f}s linear infinite}}")

    label = f"{calendar['totalContributions']} contributions eaten in the last year"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<title>Poring eating {USER}'s contribution graph</title>
<style>{"".join(css)}</style>
<rect width="100%" height="100%" rx="6" fill="{t["bg"]}"/>
{"".join(rects)}
<text x="{PAD_X}" y="{height - 10}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace" font-size="11" fill="{t["text"]}">{label}</text>
<g class="poring">{sprite}</g>
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
