"""Initial one-time import of the 2KRatings database.

IMPORTANT:
- This script is NOT used when launching NBA Manager.
- Run it once on the computer that will create the game database.
- After a successful import, data/database_initialized.json is created.
- Running it again will NOT contact 2KRatings unless --reset is explicitly used.
- The live database is replaced only after the complete import passes validation.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_FILE = DATA_DIR / "players_2k27.json"
MARKER_FILE = DATA_DIR / "database_initialized.json"
BACKUP_DIR = DATA_DIR / "backups"
SCRAPER = BASE_DIR / "scrape_2kratings.py"
TEAMS_FILE = DATA_DIR / "teams.json"

CATEGORIES = [
    "outside_scoring", "inside_scoring", "athleticism",
    "playmaking", "defense", "rebounding", "stamina"
]


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def validate_database(path: Path) -> tuple[bool, str, dict]:
    doc = load_json(path)
    if not isinstance(doc, dict):
        return False, "Le fichier JSON n'est pas valide.", {}

    players = doc.get("players")
    if not isinstance(players, dict):
        return False, "La section 'players' est absente.", {}

    teams_doc = load_json(TEAMS_FILE, {"teams": []})
    team_ids = [t["id"] for t in teams_doc.get("teams", [])]
    if len(team_ids) < 29:
        return False, f"teams.json ne contient pas assez d'équipes ({len(team_ids)} trouvées, minimum 29 requis).", {}

    missing_teams = [tid for tid in team_ids if not players.get(tid)]
    if missing_teams:
        return False, "Équipes sans joueurs : " + ", ".join(missing_teams), {}

    total = 0
    complete = 0
    teams_ok = 0
    incomplete_examples = []

    for tid in team_ids:
        roster = players.get(tid, [])
        total += len(roster)
        team_complete = 0
        for p in roster:
            missing = [k for k in CATEGORIES if p.get(k) is None]
            if not missing:
                complete += 1
                team_complete += 1
            elif len(incomplete_examples) < 10:
                incomplete_examples.append(
                    f"{tid} | {p.get('name','?')} | manque: {', '.join(missing)}"
                )
        if len(roster) >= 10 and team_complete >= 10:
            teams_ok += 1

    stats = {
        "teams": len(team_ids),
        "teams_ok": teams_ok,
        "total_players": total,
        "complete_players": complete,
        "incomplete_players": total - complete,
    }

    # The game needs a usable roster for every franchise.
    if teams_ok != 30:
        detail = (
            f"Seulement {teams_ok}/30 équipes ont au moins 10 joueurs avec "
            f"les {len(CATEGORIES)} catégories complètes."
        )
        if incomplete_examples:
            detail += "\nExemples:\n- " + "\n- ".join(incomplete_examples)
        return False, detail, stats

    return True, "Base complète et exploitable.", stats


def backup_current():
    if not DB_FILE.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    target = BACKUP_DIR / f"players_2k27_before_initial_import_{stamp}.json"
    shutil.copy2(DB_FILE, target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Autorise exceptionnellement une nouvelle récupération après initialisation."
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if MARKER_FILE.exists() and not args.reset:
        meta = load_json(MARKER_FILE, {})
        print("========================================")
        print("NBA MANAGER - BASE DEJA INITIALISEE")
        print("========================================")
        print("La base 2KRatings a déjà été récupérée.")
        print(f"Date : {meta.get('initialized_at', 'inconnue')}")
        print("Aucune connexion à 2KRatings n'a été effectuée.")
        print()
        print("Le jeu utilise directement data/players_2k27.json.")
        print("Pour une nouvelle récupération exceptionnelle :")
        print("  python setup_database.py --reset")
        return 0

    print("========================================")
    print("NBA MANAGER - IMPORT INITIAL 2KRATINGS")
    print("========================================")
    print()
    print("Cette opération récupère une seule fois les données nécessaires.")
    print("Elle peut prendre plusieurs minutes.")
    print("Pendant cette opération, le jeu ne doit pas être lancé.")
    print()

    # Scraper writes a temporary database so an incomplete scrape can never
    # destroy the currently usable local database.
    temp_file = DATA_DIR / "players_2k27_importing.json"
    old_file = DB_FILE
    temp_backup = DATA_DIR / "players_2k27_original_before_import.json"

    if temp_file.exists():
        temp_file.unlink()

    # Tell the scraper to write to the temporary file through an environment
    # variable rather than changing its normal runtime database path.
    import os
    env = os.environ.copy()
    env["NBA_MANAGER_SCRAPE_OUTPUT"] = str(temp_file)

    command = [sys.executable, str(SCRAPER), "--refresh", "--workers", "6", "--delay", "0.35"]
    result = subprocess.run(command, cwd=BASE_DIR, env=env)

    if result.returncode != 0 or not temp_file.exists():
        print()
        print("❌ L'import a échoué.")
        print("La base locale existante n'a pas été remplacée.")
        return result.returncode or 1

    ok, message, stats = validate_database(temp_file)
    print()
    print("Validation de la nouvelle base...")
    print(message)
    print(f"Équipes : {stats.get('teams', 0)}/30")
    print(f"Joueurs : {stats.get('total_players', 0)}")
    print(f"Joueurs complets : {stats.get('complete_players', 0)}")

    if not ok:
        temp_file.unlink(missing_ok=True)
        print()
        print("❌ Validation échouée.")
        print("La base existante reste inchangée.")
        return 1

    backup = backup_current()

    # Atomic-ish replacement: move the validated import into the real filename
    # only after all checks have passed.
    if DB_FILE.exists():
        DB_FILE.unlink()
    temp_file.replace(DB_FILE)

    meta = {
        "source": "2KRatings",
        "edition": "NBA 2K27",
        "initialized_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "database_file": "data/players_2k27.json",
        "policy": "one_time_import",
        "total_players": stats["total_players"],
        "complete_players": stats["complete_players"],
        "teams": 30,
    }
    MARKER_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("========================================")
    print("✅ BASE INITIALISEE AVEC SUCCES")
    print("========================================")
    print("La recherche 2KRatings est maintenant terminée.")
    print("Le jeu n'effectuera plus aucune recherche au lancement.")
    print(f"Base locale : {DB_FILE}")
    if backup:
        print(f"Ancienne base sauvegardée : {backup}")
    print()
    print("Tu peux maintenant distribuer le dossier du jeu à tes amis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
