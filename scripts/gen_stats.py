#!/usr/bin/env python3
"""
insert3coins — self-hosted GitHub stats card generator.

Queries the GitHub GraphQL API and writes SVG cards into assets/.
No third-party services, no pip dependencies — stdlib only.

Run locally:   GITHUB_TOKEN=ghp_xxx GH_USER=insert3coins python3 scripts/gen_stats.py
In Actions:    handled by .github/workflows/stats.yml
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

# ── palette ──────────────────────────────────────────────────────────────
VOID    = "#0D0619"
PANEL   = "#140A24"
CYAN    = "#21E6C1"
MAGENTA = "#FF4F9A"
AMBER   = "#FFB24D"
TEXT    = "#C9D1D9"
DIM     = "#6E5A8A"

FONT = "'Share Tech Mono','Consolas','Courier New',monospace"

API = "https://api.github.com/graphql"

QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    name
    followers { totalCount }
    following { totalCount }
    pullRequests(first: 1) { totalCount }
    issues(first: 1) { totalCount }
    contributionsCollection {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount weekday } }
      }
    }
    repositories(
      first: 100, after: $cursor,
      ownerAffiliations: OWNER, isFork: false,
      orderBy: {field: STARGAZERS, direction: DESC}
    ) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        description
        stargazerCount
        forkCount
        primaryLanguage { name color }
        languages(first: 12, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


def graphql(token, login, cursor=None):
    body = json.dumps({"query": QUERY,
                       "variables": {"login": login, "cursor": cursor}}).encode()
    req = urllib.request.Request(API, data=body, method="POST", headers={
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": f"{login}-selfhosted-stats",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    if "errors" in payload:
        sys.exit(f"GraphQL error: {payload['errors']}")
    return payload["data"]["user"]


def collect(token, login):
    """Walk every page of repos and total everything up."""
    stars = forks = 0
    langs = {}
    repo_count = 0
    repo_nodes = []
    cursor = None
    user = None

    while True:
        user = graphql(token, login, cursor)
        repos = user["repositories"]
        repo_count = repos["totalCount"]
        for node in repos["nodes"]:
            repo_nodes.append(node)
            stars += node["stargazerCount"]
            forks += node["forkCount"]
            for edge in node["languages"]["edges"]:
                name = edge["node"]["name"]
                entry = langs.setdefault(
                    name, {"size": 0, "color": edge["node"]["color"] or DIM})
                entry["size"] += edge["size"]
        if not repos["pageInfo"]["hasNextPage"]:
            break
        cursor = repos["pageInfo"]["endCursor"]

    contrib = user["contributionsCollection"]
    cal = contrib["contributionCalendar"]
    return {
        "login": login,
        "stars": stars,
        "forks": forks,
        "repos": repo_count,
        "repo_nodes": repo_nodes,
        "followers": user["followers"]["totalCount"],
        "commits": (contrib["totalCommitContributions"]
                    + contrib["restrictedContributionsCount"]),
        "prs": user["pullRequests"]["totalCount"],
        "issues": user["issues"]["totalCount"],
        "contributions": cal["totalContributions"],
        "weeks": cal["weeks"],
        "langs": langs,
    }


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def frame(width, height, title, body, glow=True):
    """Shared card chrome: void panel, neon border, scanlines, title bar."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"
     viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">
  <defs>
    <linearGradient id="edge" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{CYAN}"/>
      <stop offset="55%" stop-color="{MAGENTA}"/>
      <stop offset="100%" stop-color="{AMBER}"/>
    </linearGradient>
    <pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse">
      <rect width="4" height="1" fill="{CYAN}" opacity="0.035"/>
    </pattern>
    {'<filter id="glow"><feGaussianBlur stdDeviation="2.2" result="b"/>'
     '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/>'
     '</feMerge></filter>' if glow else ''}
  </defs>

  <rect x="1" y="1" width="{width-2}" height="{height-2}" rx="10"
        fill="{VOID}" stroke="url(#edge)" stroke-width="2"/>
  <rect x="1" y="1" width="{width-2}" height="{height-2}" rx="10" fill="url(#scan)"/>

  <text x="22" y="34" font-family="{FONT}" font-size="15" fill="{CYAN}"
        letter-spacing="2"{' filter="url(#glow)"' if glow else ''}>{esc(title)}</text>
  <line x1="22" y1="45" x2="{width-22}" y2="45" stroke="{DIM}" stroke-width="1" opacity="0.5"/>

{body}
</svg>
"""


def card_stats(d):
    rows = [
        ("TOTAL STARS",     d["stars"],         AMBER),
        ("COMMITS (YR)",    d["commits"],       CYAN),
        ("PULL REQUESTS",   d["prs"],           MAGENTA),
        ("ISSUES",          d["issues"],        CYAN),
        ("PUBLIC REPOS",    d["repos"],         AMBER),
        ("FOLLOWERS",       d["followers"],     MAGENTA),
    ]
    W, H = 460, 230
    out = []
    y = 74
    for i, (label, value, color) in enumerate(rows):
        out.append(
            f'  <text x="26" y="{y}" font-family="{FONT}" font-size="13" '
            f'fill="{TEXT}" letter-spacing="1">{esc(label)}</text>'
        )
        # dotted leader so it reads like a scoreboard
        out.append(
            f'  <line x1="200" y1="{y-4}" x2="{W-96}" y2="{y-4}" stroke="{DIM}" '
            f'stroke-width="1" stroke-dasharray="2 4" opacity="0.55"/>'
        )
        out.append(
            f'  <text x="{W-26}" y="{y}" font-family="{FONT}" font-size="14" '
            f'fill="{color}" text-anchor="end" font-weight="bold">'
            f'{value:,}<animate attributeName="opacity" values="0;1" dur="0.4s" '
            f'begin="{i*0.09:.2f}s" fill="freeze"/></text>'
        )
        y += 25

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out.append(
        f'  <text x="26" y="{H-16}" font-family="{FONT}" font-size="9" '
        f'fill="{DIM}">SELF-HOSTED // UPDATED {stamp}</text>'
    )
    return frame(W, H, f"> {d['login'].upper()} :: STATS", "\n".join(out))


def card_langs(d, top=6):
    langs = sorted(d["langs"].items(), key=lambda kv: kv[1]["size"], reverse=True)[:top]
    total = sum(v["size"] for _, v in langs) or 1
    W, H = 400, 230
    out = []

    # stacked bar
    bx, by, bw, bh = 26, 62, W - 52, 12
    out.append(f'  <rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="6" fill="{PANEL}"/>')
    out.append(f'  <clipPath id="barclip"><rect x="{bx}" y="{by}" width="{bw}" '
               f'height="{bh}" rx="6"/></clipPath>')
    out.append('  <g clip-path="url(#barclip)">')
    x = bx
    for name, v in langs:
        seg = bw * v["size"] / total
        out.append(f'    <rect x="{x:.1f}" y="{by}" width="{seg:.1f}" height="{bh}" '
                   f'fill="{v["color"]}"/>')
        x += seg
    out.append('  </g>')

    # legend, two columns
    y = 104
    for i, (name, v) in enumerate(langs):
        pct = 100 * v["size"] / total
        col = i % 2
        cx = 26 + col * (W // 2 - 20)
        cy = y + (i // 2) * 28
        out.append(f'  <rect x="{cx}" y="{cy-9}" width="10" height="10" rx="2" '
                   f'fill="{v["color"]}"/>')
        out.append(f'  <text x="{cx+18}" y="{cy}" font-family="{FONT}" font-size="12" '
                   f'fill="{TEXT}">{esc(name)}</text>')
        out.append(f'  <text x="{cx+18}" y="{cy+14}" font-family="{FONT}" font-size="10" '
                   f'fill="{DIM}">{pct:.1f}%</text>')

    kb = total / 1024
    size = f"{kb/1024:.1f} MB" if kb > 1024 else f"{kb:.0f} KB"
    out.append(f'  <line x1="26" y1="{H-32}" x2="{W-26}" y2="{H-32}" stroke="{DIM}" '
               f'stroke-width="1" stroke-dasharray="2 4" opacity="0.45"/>')
    out.append(f'  <text x="26" y="{H-16}" font-family="{FONT}" font-size="9" '
               f'fill="{DIM}">{len(d["langs"])} LANGUAGES // {size} OF SOURCE</text>')

    return frame(W, H, "> LANGUAGE MIX", "\n".join(out))


def wrap(text, width):
    """Naive word wrap into a list of lines."""
    words, lines, cur = str(text or "").split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if len(trial) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def card_repo(node):
    """Pin-style card for a single repository."""
    W, H = 420, 140
    name = node["name"]
    lang = node.get("primaryLanguage") or {}
    out = []

    desc = wrap(node.get("description") or "No description.", 52)[:3]
    y = 72
    for line in desc:
        out.append(f'  <text x="26" y="{y}" font-family="{FONT}" font-size="11.5" '
                   f'fill="{TEXT}">{esc(line)}</text>')
        y += 17

    fy = H - 20
    if lang.get("name"):
        out.append(f'  <circle cx="31" cy="{fy-4}" r="5" fill="{lang.get("color") or DIM}"/>')
        out.append(f'  <text x="43" y="{fy}" font-family="{FONT}" font-size="11" '
                   f'fill="{TEXT}">{esc(lang["name"])}</text>')

    out.append(f'  <text x="{W-26}" y="{fy}" font-family="{FONT}" font-size="11" '
               f'fill="{AMBER}" text-anchor="end">'
               f'★ {node["stargazerCount"]}   ⑂ {node["forkCount"]}</text>')

    return frame(W, H, f"> {name.upper()}", "\n".join(out))


def card_calendar(d):
    """The last year of contributions, drawn in our own palette."""
    weeks = d["weeks"]
    cell, gap = 11, 2
    step = cell + gap
    left, top = 26, 76
    W = left * 2 + len(weeks) * step
    H = top + 7 * step + 46

    counts = [day["contributionCount"]
              for w in weeks for day in w["contributionDays"]]
    peak = max(counts) if counts else 0

    # five-step ramp: void -> purple -> magenta -> amber -> cyan
    ramp = ["#1A0B2E", "#3D2A5C", "#FF4F9A", "#FFB24D", "#21E6C1"]

    def shade(n):
        if n == 0 or peak == 0:
            return ramp[0]
        q = n / peak
        if q <= 0.25:
            return ramp[1]
        if q <= 0.50:
            return ramp[2]
        if q <= 0.75:
            return ramp[3]
        return ramp[4]

    out = []
    months = {}
    for wi, w in enumerate(weeks):
        for day in w["contributionDays"]:
            x = left + wi * step
            y = top + day["weekday"] * step
            n = day["contributionCount"]
            out.append(
                f'  <rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" '
                f'fill="{shade(n)}"><title>{day["date"]}: {n}</title></rect>'
            )
        first = w["contributionDays"][0]["date"]
        mon = first[:7]
        if mon not in months:
            months[mon] = wi

    for mon, wi in months.items():
        label = datetime.strptime(mon, "%Y-%m").strftime("%b").upper()
        out.append(f'  <text x="{left + wi*step}" y="{top-8}" font-family="{FONT}" '
                   f'font-size="9" fill="{DIM}">{label}</text>')

    ly = top + 7 * step + 20
    out.append(f'  <text x="{left}" y="{ly}" font-family="{FONT}" font-size="10" '
               f'fill="{TEXT}">{d["contributions"]:,} CONTRIBUTIONS IN THE LAST YEAR</text>')
    lx = W - left - len(ramp) * 15 - 46
    out.append(f'  <text x="{lx-6}" y="{ly}" font-family="{FONT}" font-size="9" '
               f'fill="{DIM}" text-anchor="end">LESS</text>')
    for i, c in enumerate(ramp):
        out.append(f'  <rect x="{lx + i*15}" y="{ly-9}" width="11" height="11" rx="2" fill="{c}"/>')
    out.append(f'  <text x="{lx + len(ramp)*15 + 6}" y="{ly}" font-family="{FONT}" '
               f'font-size="9" fill="{DIM}">MORE</text>')

    return frame(W, H, "> CONTRIBUTION GRID :: LAST 365 DAYS", "\n".join(out))


def main():
    token = os.environ.get("GITHUB_TOKEN")
    login = os.environ.get("GH_USER", "insert3coins")
    if not token:
        sys.exit("GITHUB_TOKEN is not set.")

    data = collect(token, login)
    os.makedirs("assets", exist_ok=True)

    written = []
    for path, svg in [
        ("assets/stats.svg",    card_stats(data)),
        ("assets/langs.svg",    card_langs(data)),
        ("assets/calendar.svg", card_calendar(data)),
    ]:
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
        written.append(path)

    # one card per public source repo, capped at the top 6 by stars
    for node in data["repo_nodes"][:6]:
        if node["name"].lower() == login.lower():
            continue          # skip the profile repo itself
        path = f"assets/repo-{node['name']}.svg"
        with open(path, "w", encoding="utf-8") as f:
            f.write(card_repo(node))
        written.append(path)

    print("wrote:\n  " + "\n  ".join(written))
    print(json.dumps({k: v for k, v in data.items()
                      if k not in ("langs", "weeks", "repo_nodes")}, indent=2))


if __name__ == "__main__":
    main()
