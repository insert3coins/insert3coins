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
      orderBy: {field: PUSHED_AT, direction: DESC}
    ) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        description
        url
        pushedAt
        isArchived
        stargazerCount
        forkCount
        primaryLanguage { name color }
        repositoryTopics(first: 10) { nodes { topic { name } } }
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


# ── README auto-injection ────────────────────────────────────────────────
CABS_START = "<!-- CABS:START -->"
CABS_END   = "<!-- CABS:END -->"


def render_cabs(repos, login, branch):
    """Build the generated card block that goes between the markers."""
    base = (f"https://raw.githubusercontent.com/{login}/{login}"
            f"/{branch}/assets")
    out = ["", '<div align="center">', ""]
    for r in repos:
        out.append(f'<a href="{r["url"]}">')
        out.append(f'  <img src="{base}/repo-{r["name"]}.svg" '
                   f'alt="{esc(r["name"])}" width="420" />')
        out.append("</a>")
    out += ["", "</div>", ""]
    return "\n".join(out)


TABLE_START = "<!-- CABTABLE:START -->"
TABLE_END   = "<!-- CABTABLE:END -->"

OVERRIDES_FILE = "cabinet.json"
DEFAULT_ICON = "🕹️"


def load_overrides():
    """Optional per-repo icon/blurb, keyed by repo name. Missing file is fine."""
    if not os.path.exists(OVERRIDES_FILE):
        return {}
    try:
        with open(OVERRIDES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARNING: could not read {OVERRIDES_FILE} ({e}) — using defaults.")
        return {}


def hardware_tags(node, limit=3):
    """Prefer hand-picked repo topics; fall back to detected languages."""
    topics = [t["topic"]["name"]
              for t in node.get("repositoryTopics", {}).get("nodes", [])]
    if topics:
        return topics[:limit]
    return [e["node"]["name"] for e in node["languages"]["edges"][:limit]]


def cell(text):
    """Markdown tables break on raw pipes and newlines."""
    return (str(text or "").replace("|", "\\|")
            .replace("\n", " ").replace("\r", " ").strip())


def render_table(repos, overrides):
    rows = ["", "| CAB | GAME | HARDWARE |", "|:---:|:-----|:---------|"]
    for r in repos:
        ov = overrides.get(r["name"], {})
        icon = ov.get("icon", DEFAULT_ICON)
        blurb = ov.get("blurb") or r.get("description") or "No description yet."
        tags = ov.get("hardware") or hardware_tags(r)
        hw = " ".join(f"`{cell(t)}`" for t in tags) or "`—`"
        rows.append(f'| {icon} | **[{cell(r["name"])}]({r["url"]})** — '
                    f'{cell(blurb)} | {hw} |')
    rows.append("")
    return "\n".join(rows)


def replace_block(doc, start, end, payload, label):
    if start not in doc or end not in doc:
        print(f"  {label}: markers missing — skipped.")
        return doc, False
    head, rest = doc.split(start, 1)
    _, tail = rest.split(end, 1)
    return head + start + payload + end + tail, True


def update_readme(repos, login, branch, path="README.md"):
    """Rewrite the generated blocks. Everything outside markers is untouched."""
    if not os.path.exists(path):
        print(f"{path} not found — skipping injection.")
        return False

    original = open(path, encoding="utf-8").read()
    doc = original
    overrides = load_overrides()

    doc, ok_cards = replace_block(doc, CABS_START, CABS_END,
                                  render_cabs(repos, login, branch), "cards")
    doc, ok_table = replace_block(doc, TABLE_START, TABLE_END,
                                  render_table(repos, overrides), "table")

    if doc == original:
        print("README already up to date.")
        return False

    open(path, "w", encoding="utf-8").write(doc)
    print(f"README updated — cards:{ok_cards} table:{ok_table} "
          f"({len(repos)} repo(s))")
    return True


def prune_stale_cards(keep_names):
    """Delete repo-*.svg for repos that no longer exist or were renamed."""
    removed = []
    for fn in os.listdir("assets"):
        if not (fn.startswith("repo-") and fn.endswith(".svg")):
            continue
        if fn[5:-4] not in keep_names:
            os.remove(os.path.join("assets", fn))
            removed.append(fn)
    for fn in removed:
        print(f"pruned stale card: {fn}")
    return removed


def main():
    token = os.environ.get("GITHUB_TOKEN")
    login = os.environ.get("GH_USER", "insert3coins")
    branch = os.environ.get("GH_BRANCH", "main")
    max_cards = int(os.environ.get("MAX_CARDS", "6"))
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

    # Filter FIRST, then slice — otherwise the profile repo eats a card slot.
    # Already sorted most-recently-pushed first by the GraphQL query.
    showable = [n for n in data["repo_nodes"]
                if n["name"].lower() != login.lower() and not n["isArchived"]]
    featured = showable[:max_cards]

    for node in featured:
        path = f"assets/repo-{node['name']}.svg"
        with open(path, "w", encoding="utf-8") as f:
            f.write(card_repo(node))
        written.append(path)

    prune_stale_cards({n["name"] for n in featured})
    update_readme(featured, login, branch)

    print("wrote:\n  " + "\n  ".join(written))
    print("featured (newest push first): "
          + ", ".join(n["name"] for n in featured))
    print(json.dumps({k: v for k, v in data.items()
                      if k not in ("langs", "weeks", "repo_nodes")}, indent=2))


if __name__ == "__main__":
    main()
