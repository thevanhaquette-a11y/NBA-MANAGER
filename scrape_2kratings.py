"""Complete local import of current NBA 2K27 rosters + general ratings from 2KRatings.

The script is designed to be run on the user's PC, where internet access to
2KRatings is available. It downloads the current roster page for each of the
30 NBA franchises, then follows each player page and extracts:
    - OVR
    - 3PT
    - Dunk
    - Outside Scoring
    - Inside Scoring
    - Athleticism
    - Playmaking
    - Defense
    - Rebounding
    - Stamina

No value is guessed. When a rating cannot be extracted, it remains null and
is reported explicitly.

Usage:
    python scrape_2kratings.py
    python scrape_2kratings.py --team PHI
    python scrape_2kratings.py --refresh
    python scrape_2kratings.py --workers 4 --delay 0.5
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

BASE_URL = "https://www.2kratings.com"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TEAMS_FILE = DATA_DIR / "teams.json"
OUTPUT_FILE = Path(__import__("os").environ.get("NBA_MANAGER_SCRAPE_OUTPUT", str(DATA_DIR / "players_2k27.json")))
REPORT_FILE = DATA_DIR / "scrape_report.json"
CACHE_DIR = DATA_DIR / "cache_2kratings"

CATEGORY_LABELS = {
    "outside_scoring": ["OUTSIDE SCORING", "OUTSIDE"],
    "inside_scoring": ["INSIDE SCORING", "INSIDE"],
    "athleticism": ["ATHLETICISM"],
    "playmaking": ["PLAYMAKING"],
    "defense": ["DEFENSE", "DEFENDING"],
    "rebounding": ["REBOUNDING"],
    "stamina": ["STAMINA", "ENDURANCE"],
}

POSITION_RE = re.compile(
    r"\b(PG|SG|SF|PF|C)(?:\s*/\s*(PG|SG|SF|PF|C))?(?:\s*/\s*(PG|SG|SF|PF|C))?\b",
    re.I,
)

NAME_RE = re.compile(r"[A-Za-zÀ-ÿ'.’-]+(?:\s+[A-Za-zÀ-ÿ'.’-]+)+$")

print_lock = Lock()


def safe_print(*args) -> None:
    with print_lock:
        print(*args, flush=True)


def normalize(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


class TableParser(HTMLParser):
    """Small HTML parser collecting tables, cells and links."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: List[List[dict]] = []
        self._in_table = False
        self._rows: List[dict] = []
        self._row: Optional[dict] = None
        self._cell: Optional[dict] = None
        self._link: Optional[dict] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attrs_d = dict(attrs)
        if tag == "table":
            self._in_table = True
            self._rows = []
        elif self._in_table and tag == "tr":
            self._row = {"cells": []}
        elif self._in_table and tag in ("th", "td") and self._row is not None:
            self._cell = {"text": "", "links": []}
        elif self._in_table and tag == "a" and self._cell is not None:
            self._link = {"text": "", "href": attrs_d.get("href")}

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"] += data
            if self._link is not None:
                self._link["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link is not None and self._cell is not None:
            self._link["text"] = normalize(self._link["text"])
            self._cell["links"].append(self._link)
            self._link = None
        elif self._in_table and tag in ("th", "td") and self._cell is not None:
            self._cell["text"] = normalize(self._cell["text"])
            if self._row is not None:
                self._row["cells"].append(self._cell)
            self._cell = None
        elif self._in_table and tag == "tr" and self._row is not None:
            self._rows.append(self._row)
            self._row = None
        elif tag == "table" and self._in_table:
            if self._rows:
                self.tables.append(self._rows)
            self._in_table = False


class TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def fetch(url: str, retries: int = 3, timeout: int = 30) -> str:
    last: Optional[Exception] = None
    for attempt in range(retries):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/154.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml",
                    "Connection": "close",
                },
            )
            with urlopen(req, timeout=timeout) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Impossible de récupérer {url}: {last}")


def cache_path(url: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", url.replace("https://", ""))
    return CACHE_DIR / f"{safe}.html"


def cached_fetch(url: str, refresh: bool, delay: float) -> str:
    path = cache_path(url)
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8", errors="replace")
    html = fetch(url)
    if delay:
        time.sleep(delay)
    path.write_text(html, encoding="utf-8")
    return html


def is_probable_player_link(text: str, href: str) -> bool:
    text = normalize(text)
    href_l = (href or "").lower()
    if len(re.findall(r"[A-Za-zÀ-ÿ]+", text)) < 2:
        return False
    excluded = (
        "/teams/", "/current-teams", "/attributes-filter", "/players", "/collections",
        "/badges", "/leagues", "/2k-ratings", "/compare", "/search", "/ratings/teams/",
    )
    if any(token in href_l for token in excluded):
        return False
    # 2KRatings player URLs are generally simple slugs under the root.
    return href_l.startswith(BASE_URL.lower()) and "/" not in href_l[len(BASE_URL):].strip("/")


def parse_roster(team_html: str) -> List[dict]:
    parser = TableParser()
    parser.feed(team_html)
    best: List[dict] = []

    for table in parser.tables:
        if not table:
            continue
        header = " ".join(c["text"] for c in table[0]["cells"]).lower()
        if "player" not in header or "ovr" not in header:
            continue

        candidates: List[dict] = []
        for row in table[1:]:
            cells = row.get("cells", [])
            if len(cells) < 4:
                continue

            name = ""
            url = None
            for cell in cells:
                for link in cell.get("links", []):
                    t = normalize(link.get("text", ""))
                    h = urljoin(BASE_URL, link.get("href") or "")
                    if is_probable_player_link(t, h):
                        name = t
                        url = h
                        break
                if name:
                    break
            if not name:
                continue

            texts = [normalize(c["text"]) for c in cells]
            numbers: List[int] = []
            for t in texts:
                if re.fullmatch(r"\d{1,3}", t):
                    numbers.append(int(t))

            if len(numbers) < 3:
                continue

            position_match = POSITION_RE.search(" ".join(texts))
            position = "/".join(
                g.upper() for g in (position_match.groups() if position_match else ()) if g
            )

            # Roster table columns end with OVR, 3PT, DNK on the current site.
            candidates.append({
                "name": name,
                "position": position,
                "overall": numbers[-3],
                "three_point": numbers[-2],
                "dunk": numbers[-1],
                "url": url,
            })

        if len(candidates) > len(best):
            best = candidates

    # De-duplicate by player name while keeping first occurrence.
    seen = set()
    out = []
    for p in best:
        key = normalize(p["name"]).lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def html_to_text(html: str) -> str:
    p = TextParser()
    p.feed(html)
    return normalize(" ".join(p.parts))


def extract_rating(text: str, labels: List[str]) -> Optional[int]:
    upper = normalize(text).upper()
    for label in labels:
        escaped = re.escape(label)
        patterns = [
            rf"{escaped}\s*[:\-]?\s*(\d{{1,3}})\b",
            rf"(\d{{1,3}})\s*[:\-]?\s*{escaped}\b",
            rf"{escaped}[^0-9]{{0,80}}(\d{{1,3}})\b",
        ]
        for pattern in patterns:
            m = re.search(pattern, upper, flags=re.I)
            if m:
                value = int(m.group(1))
                if 0 <= value <= 100:
                    return value
    return None


def parse_general_categories(player_html: str) -> Dict[str, Optional[int]]:
    text = html_to_text(player_html)
    return {
        key: extract_rating(text, labels)
        for key, labels in CATEGORY_LABELS.items()
    }


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def enrich_player(player: dict, refresh: bool, delay: float) -> dict:
    record = dict(player)
    record.update({key: None for key in CATEGORY_LABELS})
    record["general_category_status"] = "unverified"
    record["source"] = "2KRatings"

    if not player.get("url"):
        record["detail_error"] = "Aucun lien joueur trouvé sur la page équipe"
        return record

    try:
        html = cached_fetch(player["url"], refresh=refresh, delay=delay)
        categories = parse_general_categories(html)
        record.update(categories)
        record["general_category_status"] = (
            "verified" if all(v is not None for v in categories.values()) else "partial"
        )
    except Exception as exc:
        record["detail_error"] = str(exc)
    return record


def main() -> int:
    ap = argparse.ArgumentParser(description="Import complet des ratings NBA 2K27 depuis 2KRatings")
    ap.add_argument("--team", help="ID d'équipe, ex. PHI")
    ap.add_argument("--delay", type=float, default=0.45, help="Délai entre requêtes, défaut 0.45 s")
    ap.add_argument("--workers", type=int, default=4, help="Nombre de requêtes joueur simultanées, défaut 4")
    ap.add_argument("--refresh", action="store_true", help="Ignore le cache HTML")
    args = ap.parse_args()
    args.workers = max(1, min(8, args.workers))

    teams_doc = load_json(TEAMS_FILE, {"teams": []})
    teams = teams_doc.get("teams", [])
    selected = [t for t in teams if not args.team or t["id"].upper() == args.team.upper()]
    if args.team and not selected:
        print(f"Equipe inconnue : {args.team}", file=sys.stderr)
        return 2

    existing = load_json(OUTPUT_FILE, {"source": "2KRatings", "edition": "NBA 2K27", "players": {}})
    players_by_team = existing.get("players", {}) if not args.refresh else existing.get("players", {})
    report = []

    print(f"Import 2KRatings NBA 2K27 : {len(selected)} équipe(s)")
    print(f"Workers : {args.workers} | Délai : {args.delay}s")

    for team in selected:
        team_id = team["id"]
        team_url = f"{BASE_URL}/teams/{team['slug']}"
        safe_print(f"\n🏀 {team['name']}")
        try:
            team_html = cached_fetch(team_url, refresh=args.refresh, delay=args.delay)
            roster = parse_roster(team_html)
        except Exception as exc:
            report.append({"team": team_id, "status": "error", "error": str(exc)})
            safe_print(f"❌ Page équipe : {exc}")
            continue

        if not roster:
            report.append({"team": team_id, "status": "no_roster_found"})
            safe_print("⚠️ Aucun roster détecté")
            continue

        out_players: List[Optional[dict]] = [None] * len(roster)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(enrich_player, player, args.refresh, args.delay): i
                for i, player in enumerate(roster)
            }
            completed = 0
            for future in as_completed(futures):
                i = futures[future]
                try:
                    out_players[i] = future.result()
                except Exception as exc:
                    out_players[i] = dict(roster[i], general_category_status="unverified", detail_error=str(exc))
                completed += 1
                rec = out_players[i]
                safe_print(f"  [{completed}/{len(roster)}] {rec['name']} -> {rec.get('general_category_status')}")

        final_players = [p for p in out_players if p is not None]
        players_by_team[team_id] = final_players
        verified = sum(p.get("general_category_status") == "verified" for p in final_players)
        missing = {
            key: sum(p.get(key) is None for p in final_players)
            for key in CATEGORY_LABELS
        }
        report.append({
            "team": team_id,
            "name": team["name"],
            "status": "ok",
            "players": len(final_players),
            "fully_verified": verified,
            "partial_or_unverified": len(final_players) - verified,
            "missing_by_category": missing,
        })

    # Preserve the complete 30-team structure. Teams not selected remain unchanged.
    ordered_players = {t["id"]: players_by_team.get(t["id"], []) for t in teams}
    output = {
        "source": "2KRatings",
        "edition": "NBA 2K27",
        "updated_from_live_site_by_script": True,
        "categories": [
            "outside_scoring", "inside_scoring", "athleticism", "playmaking",
            "defense", "rebounding", "stamina",
        ],
        "teams_count": len(teams),
        "players": ordered_players,
    }
    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    total_players = sum(len(v) for v in ordered_players.values())
    total_verified = sum(
        p.get("general_category_status") == "verified"
        for plist in ordered_players.values() for p in plist
    )
    missing_players = [
        {"team": tid, "name": p.get("name"), "missing": [k for k in CATEGORY_LABELS if p.get(k) is None]}
        for tid, plist in ordered_players.items()
        for p in plist if any(p.get(k) is None for k in CATEGORY_LABELS)
    ]

    full_report = {
        "source": "2KRatings",
        "edition": "NBA 2K27",
        "team_count": len(teams),
        "teams_with_data": sum(bool(ordered_players[t["id"]]) for t in teams),
        "total_players": total_players,
        "fully_verified_players": total_verified,
        "players_with_missing_general_category": len(missing_players),
        "missing_players": missing_players,
        "runs": report,
    }
    REPORT_FILE.write_text(json.dumps(full_report, ensure_ascii=False, indent=2), encoding="utf-8")

    safe_print("\n✅ Import terminé")
    safe_print(f"Équipes dans la base : {len(teams)}")
    safe_print(f"Joueurs enregistrés : {total_players}")
    safe_print(f"Joueurs avec les 7 catégories : {total_verified}")
    safe_print(f"Joueurs avec au moins une note manquante : {len(missing_players)}")
    safe_print(f"Base : {OUTPUT_FILE}")
    safe_print(f"Rapport : {REPORT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
