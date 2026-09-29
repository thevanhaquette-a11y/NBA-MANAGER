from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import json
from itertools import combinations

from main import (
    DEFAULT_TACTICS,
    Player,
    Team,
    simulate_game,
    position_assignment,
    infer_natural_role,
    build_default_rotation_minutes,
    build_feasible_rotation,
    set_rotation_plan,
    REQUIRED_POSITIONS,
    eligible_positions,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

with open(DATA_DIR / "teams.json", encoding="utf-8") as f:
    TEAM_META = json.load(f)["teams"]

with open(DATA_DIR / "players_2k27.json", encoding="utf-8") as f:
    PLAYER_DB = json.load(f)["players"]

REQUIRED_RATINGS = [
    "overall", "outside_scoring", "inside_scoring", "athleticism",
    "playmaking", "defense", "rebounding", "stamina"
]


def complete_players(team_id):
    rows = PLAYER_DB.get(team_id, [])
    return [
        row for row in rows
        if all(row.get(key) is not None for key in REQUIRED_RATINGS)
    ]


def default_role(row):
    return infer_natural_role(
        row.get("position"),
        int(row.get("overall", 0)),
        int(row.get("outside_scoring", 0)),
        int(row.get("inside_scoring", 0)),
        int(row.get("athleticism", 0)),
        int(row.get("playmaking", 0)),
        int(row.get("defense", 0)),
        int(row.get("rebounding", 0)),
        int(row.get("stamina", 0)),
    )


def make_player(row):
    return Player(
        row["name"],
        row["position"],
        default_role(row),
        int(row["overall"]),
        int(row["outside_scoring"]),
        int(row["inside_scoring"]),
        int(row["athleticism"]),
        int(row["playmaking"]),
        int(row["defense"]),
        int(row["rebounding"]),
        int(row["stamina"]),
    )


def choose_starting_five(players):
    ordered = sorted(players, key=lambda p: p.overall, reverse=True)

    def backtrack(index, chosen):
        if len(chosen) == 5:
            if position_assignment(chosen) is not None:
                return chosen[:]
            return None
        if index >= len(ordered):
            return None
        # Try the highest-rated players first, but backtrack if positions don't fit.
        for i in range(index, len(ordered)):
            candidate = ordered[i]
            chosen.append(candidate)
            result = backtrack(i + 1, chosen)
            if result is not None:
                return result
            chosen.pop()
        return None

    result = backtrack(0, [])
    if result is None:
        raise ValueError("Impossible de construire un cinq couvrant PG, SG, SF, PF et C.")
    return result


def build_team(team_id):
    meta = next((team for team in TEAM_META if team["id"] == team_id), None)
    if meta is None:
        raise ValueError(f"Équipe inconnue : {team_id}")

    rows = complete_players(team_id)
    if len(rows) < 5:
        raise ValueError(
            f"L'effectif de {meta['name']} n'est pas encore disponible dans la base locale "
            f"({len(rows)} joueurs complets, 5 minimum)."
        )

    # IMPORTANT : on conserve tout l'effectif complet. Il n'y a plus de limite à 10 joueurs.
    rows = sorted(rows, key=lambda row: int(row["overall"]), reverse=True)
    players = [make_player(row) for row in rows]
    starters = choose_starting_five(players)
    starter_names = {p.name for p in starters}
    bench = [p for p in players if p.name not in starter_names]
    return Team(meta["name"], starters, bench), players


def team_catalog():
    result = []
    for team in TEAM_META:
        rows = complete_players(team["id"])
        excluded = len(PLAYER_DB.get(team["id"], [])) - len(rows)
        result.append({
            "id": team["id"],
            "name": team["name"],
            "slug": team["slug"],
            "player_count": len(rows),
            "excluded": excluded,
            "playable": len(rows) >= 5,
        })
    return result


def clone_rotation_plan_for(team, starter_players, bench_players, starter_minutes=30):
    """Construit puis valide un plan minutes à partir d'un cinq + banc choisis."""
    minutes = {p.name: 0 for p in team.roster}
    for p in starter_players:
        minutes[p.name] = starter_minutes
    bench_minutes_total = 240 - starter_minutes * len(starter_players)
    if bench_minutes_total < 0 or not bench_players:
        return None
    base = bench_minutes_total // len(bench_players)
    remainder = bench_minutes_total % len(bench_players)
    for i, p in enumerate(bench_players):
        minutes[p.name] = base + (1 if i < remainder else 0)
    return minutes



def build_auto_rotation_minutes(team):
    """Génère rapidement une rotation automatique et la valide avec le moteur exact."""
    players = list(team.roster)
    starters = choose_starting_five(players)
    starter_names = {p.name for p in starters}
    bench = [p for p in players if p.name not in starter_names]
    if len(bench) < 5:
        raise ValueError("Il faut au moins 5 remplaçants disponibles pour la rotation automatique.")

    ordered = sorted(bench, key=lambda p: p.overall, reverse=True)
    # On construit d'abord un banc couvrant les 5 postes, puis on complète avec
    # les meilleurs joueurs. On évite les milliers de tests de combinaisons.
    selected = []
    for pos in REQUIRED_POSITIONS:
        choices = [p for p in ordered if p not in selected and pos in eligible_positions(p)]
        if choices:
            best = choices[0]
            if best not in selected:
                selected.append(best)
    for p in ordered:
        if len(selected) >= 5:
            break
        if p not in selected:
            selected.append(p)

    # Si le premier banc n'est pas réalisable, on ajoute progressivement les
    # meilleurs joueurs suivants avec une répartition plus légère.
    for bench_count in range(5, min(8, len(ordered)) + 1):
        group = selected[:]
        for p in ordered:
            if len(group) >= bench_count:
                break
            if p not in group:
                group.append(p)
        minutes = {p.name: 0 for p in players}
        for p in starters:
            minutes[p.name] = 30
        total_bench = 90
        base = total_bench // len(group)
        remainder = total_bench % len(group)
        for i, p in enumerate(group):
            minutes[p.name] = base + (1 if i < remainder else 0)
        team.rotation_plan = minutes
        try:
            build_feasible_rotation(team)
            return starters, minutes
        except ValueError:
            continue

    raise ValueError("Impossible de générer automatiquement une rotation couvrant PG, SG, SF, PF et C avec cet effectif.")

AI_STARTER_MINUTES = [34, 32, 31, 29, 28]   # 154 min, du meilleur au 5e titulaire
AI_BENCH_MINUTES = [22, 18, 17, 15, 14]     # 86 min -> total 240


def build_ai_rotation(team):
    """Rotation de l'adversaire : les meilleurs jouent le plus. Validée par le moteur exact,
    avec repli sur la répartition 30/18 si les postes ne permettent pas ce schéma."""
    starters = sorted(team.starters, key=lambda p: p.overall, reverse=True)
    starter_names = {p.name for p in starters}
    pool = sorted([p for p in team.roster if p.name not in starter_names], key=lambda p: p.overall, reverse=True)

    covering = []
    for pos in REQUIRED_POSITIONS:
        pick = next((p for p in pool if p not in covering and pos in eligible_positions(p)), None)
        if pick:
            covering.append(pick)
    for p in pool:
        if len(covering) >= 5:
            break
        if p not in covering:
            covering.append(p)
    covering.sort(key=lambda p: p.overall, reverse=True)

    for bench in (pool[:5], covering[:5]):
        if len(bench) < 5:
            continue
        minutes = {p.name: 0 for p in team.roster}
        for p, m in zip(starters, AI_STARTER_MINUTES):
            minutes[p.name] = m
        for p, m in zip(bench, AI_BENCH_MINUTES):
            minutes[p.name] = m
        team.rotation_plan = minutes
        try:
            build_feasible_rotation(team)
            return minutes
        except ValueError:
            continue
    return build_default_rotation_minutes(team.roster, team.starters)


def ai_tactics(opponent_team, user_team=None):
    """Tactiques de l'IA basées sur le matchup contre l'utilisateur.
    Si user_team est fourni, l'IA adapte ses tactiques en fonction des faiblesses de l'utilisateur.
    Sinon, elle utilise son profil offensif par défaut.
    """
    from main import perimeter_defense, interior_defense
    tactics = DEFAULT_TACTICS.copy()
    
    # Forces offensives de l'IA
    opponent_outside = sum(p.outside_scoring for p in opponent_team.starters) / 5
    opponent_inside = sum(p.inside_scoring for p in opponent_team.starters) / 5
    
    # Si on connaît l'équipe utilisateur, analyser le matchup
    if user_team:
        # Faiblesses défensives de l'utilisateur
        user_perimeter_def = sum(perimeter_defense(p) for p in user_team.starters) / 5
        user_interior_def = sum(interior_defense(p) for p in user_team.starters) / 5
        
        # Avantages offensifs de l'IA
        outside_adv = opponent_outside - user_perimeter_def
        inside_adv = opponent_inside - user_interior_def
        
        # Choisir la tactique en fonction de l'avantage le plus fort
        if inside_adv > outside_adv + 3:  # Seuil baissé de 5 à 3
            tactics["offenseStyle"] = "Jeu intérieur"
            tactics["postUpFrequency"] = "Fréquent"
            tactics["threePointFocus"] = "Limité"
            tactics["defensivePriority"] = "Protéger peinture"
        elif outside_adv > inside_adv + 3:  # Seuil baissé de 5 à 3
            tactics["offenseStyle"] = "Pace & Space"
            tactics["threePointFocus"] = "Accentué"
            tactics["defensivePriority"] = "Limiter 3 pts"
        else:  # Équilibre - utiliser la Force Réelle (tous attributs)
            # Calculer la Force Réelle intérieure vs extérieure
            opponent_force_inside = sum(
                p.inside_scoring * 0.4 + p.rebounding * 0.2 + p.athleticism * 0.2 + p.defense * 0.2
                for p in opponent_team.starters
            ) / 5
            opponent_force_outside = sum(
                p.outside_scoring * 0.4 + p.playmaking * 0.2 + p.athleticism * 0.2 + p.defense * 0.2
                for p in opponent_team.starters
            ) / 5
            if opponent_force_inside > opponent_force_outside:
                tactics["offenseStyle"] = "Jeu intérieur"
                tactics["postUpFrequency"] = "Normal"
                tactics["defensivePriority"] = "Protéger peinture"
            else:
                tactics["offenseStyle"] = "Adresse extérieure"
                tactics["threePointFocus"] = "Normal"
                tactics["defensivePriority"] = "Limiter 3 pts"
        
        # Tactiques défensives : cibler la force de l'utilisateur
        if user_team.starters and max(p.outside_scoring for p in user_team.starters) > 75:
            tactics["defensivePriority"] = "Limiter 3 pts"
        else:
            tactics["defensivePriority"] = "Protéger peinture"
    else:
        # Sans info sur l'utilisateur, utiliser le profil seul
        if opponent_inside > opponent_outside + 3:  # Seuil baissé de 5 à 3
            tactics["offenseStyle"] = "Jeu intérieur"
            tactics["postUpFrequency"] = "Fréquent"
            tactics["defensivePriority"] = "Protéger peinture"
        elif opponent_outside > opponent_inside + 3:  # Seuil baissé de 5 à 3
            tactics["offenseStyle"] = "Pace & Space"
            tactics["threePointFocus"] = "Accentué"
            tactics["defensivePriority"] = "Limiter 3 pts"
        else:
            tactics["offenseStyle"] = "Équilibré"
            tactics["defensivePriority"] = "Équilibrée"
    
    return tactics


def roster_timeline_from_team(team):
    """Retourne la timeline de pré-match issue du plan de rotation validé."""
    if len(getattr(team, "rotation_schedule", [])) != 48 or len(getattr(team, "rotation_position_schedule", [])) != 48:
        set_rotation_plan(team, team.rotation_plan)
    timeline = []
    for minute, assignment in enumerate(team.rotation_position_schedule):
        timeline.append({
            "minute": minute + 1,
            "quarter": minute // 12 + 1,
            "minute_in_quarter": minute % 12 + 1,
            "players": [
                {"position": pos, "name": assignment[pos].name, "role": assignment[pos].role}
                for pos in ["PG", "SG", "SF", "PF", "C"]
            ],
        })
    return timeline


def serialize_roster(team_id):
    rows = complete_players(team_id)
    rows = sorted(rows, key=lambda row: int(row["overall"]), reverse=True)
    if len(rows) < 5:
        return {"success": False, "message": f"Effectif insuffisant : {len(rows)} joueurs complets (5 minimum)."}
    players = [make_player(row) for row in rows]
    starters = choose_starting_five(players)
    starter_names = {p.name for p in starters}
    active_bench = []
    for pos in REQUIRED_POSITIONS:
        choices = [p for p in players if p.name not in starter_names and pos in p.position.split("/") and p not in active_bench]
        if choices:
            active_bench.append(max(choices, key=lambda p: p.overall))
    for p in sorted(players, key=lambda x: x.overall, reverse=True):
        if p.name not in starter_names and p not in active_bench and len(active_bench) < 5:
            active_bench.append(p)
    remaining = 90
    plan = {p.name: 0 for p in players}
    for p in starters:
        plan[p.name] = 30
    if active_bench:
        base = remaining // len(active_bench)
        for i, p in enumerate(active_bench):
            plan[p.name] = base + (1 if i < remaining % len(active_bench) else 0)
    output = []
    for row in rows:
        output.append({
            "name": row["name"], "position": row["position"], "overall": row["overall"],
            "outside": row["outside_scoring"], "inside": row["inside_scoring"],
            "athleticism": row["athleticism"], "playmaking": row["playmaking"],
            "defense": row["defense"], "rebounding": row["rebounding"], "stamina": row["stamina"],
            "role": default_role(row), "minutes": plan[row["name"]], "starter": row["name"] in starter_names,
        })
    return {"success": True, "players": output, "roster_size": len(output)}

def rotation_preview(team_id, rotation_rows):
    """Construit une projection minute par minute avant le match.

    Cette projection utilise exactement le même générateur de rotations que le
    moteur : les minutes saisies par le manager déterminent les lineups possibles.
    Elle sert à visualiser qui devrait jouer ensemble ; les événements du match
    peuvent toutefois provoquer des ajustements exceptionnels (fautes).
    """
    team, _ = build_team(team_id)
    by_name = {p.name: p for p in team.roster}
    rotation = {}
    starter_names = []
    for row in rotation_rows:
        name = row.get("name")
        if name not in by_name:
            raise ValueError(f"Joueur inconnu dans la rotation : {name}")
        rotation[name] = int(row.get("minutes", 0))
        if bool(row.get("starter")):
            starter_names.append(name)
    if set(rotation) != set(by_name):
        raise ValueError("La projection doit contenir tout l'effectif.")
    if len(starter_names) != 5:
        raise ValueError("Il faut exactement 5 titulaires.")
    team.starters = [by_name[n] for n in starter_names]
    team.bench = [p for p in team.roster if p.name not in set(starter_names)]
    if position_assignment(team.starters) is None:
        raise ValueError("Le cinq majeur doit couvrir PG, SG, SF, PF et C.")
    set_rotation_plan(team, rotation)
    timeline = []
    for minute, lineup in enumerate(team.rotation_schedule):
        assignment = team.rotation_position_schedule[minute]
        timeline.append({
            "minute": minute + 1,
            "quarter": minute // 12 + 1,
            "minute_in_quarter": minute % 12 + 1,
            "players": [
                {"position": pos, "name": assignment[pos].name, "role": assignment[pos].role}
                for pos in ["PG", "SG", "SF", "PF", "C"]
            ]
        })
    return timeline


class Server(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/version":
            self.send_json(200, {"success": True, "version": "V38"})
            return
        if parsed.path == "/api/teams":
            self.send_json(200, {"success": True, "teams": team_catalog()})
            return

        if parsed.path == "/api/roster":
            team_id = parse_qs(parsed.query).get("team_id", [None])[0]
            if not team_id:
                self.send_json(400, {"success": False, "message": "team_id manquant."})
                return
            payload = serialize_roster(team_id)
            self.send_json(200 if payload["success"] else 400, payload)
            return

        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/auto-rotation":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                team_id = payload.get("team_id")
                team, _ = build_team(team_id)
                starters, rotation = build_auto_rotation_minutes(team)
                starter_names = {p.name for p in starters}
                for p in team.roster:
                    p.role = infer_natural_role(
                        p.position, p.overall, p.outside_scoring, p.inside_scoring,
                        p.athleticism, p.playmaking, p.defense, p.rebounding, p.stamina
                    )
                set_rotation_plan(team, rotation)
                rows = []
                for p in team.roster:
                    rows.append({
                        "name": p.name,
                        "position": p.position,
                        "overall": p.overall,
                        "outside": p.outside_scoring,
                        "inside": p.inside_scoring,
                        "athleticism": p.athleticism,
                        "playmaking": p.playmaking,
                        "defense": p.defense,
                        "rebounding": p.rebounding,
                        "stamina": p.stamina,
                        "role": p.role,
                        "minutes": rotation[p.name],
                        "starter": p.name in starter_names,
                    })
                self.send_json(200, {
                    "success": True,
                    "players": rows,
                    "timeline": roster_timeline_from_team(team),
                })
            except Exception as error:
                self.send_json(400, {"success": False, "message": str(error)})
            return

        if self.path == "/api/rotation-preview":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                timeline = rotation_preview(payload.get("team_id"), payload.get("rotation", []))
                self.send_json(200, {"success": True, "timeline": timeline})
            except Exception as error:
                self.send_json(400, {"success": False, "message": str(error)})
            return

        if self.path != "/rotation":
            self.send_json(404, {"success": False, "message": "Route inconnue."})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))

            user_team_id = payload.get("team1_id")
            opponent_team_id = payload.get("team2_id")
            if not user_team_id or not opponent_team_id:
                raise ValueError("Les deux équipes doivent être sélectionnées.")
            if user_team_id == opponent_team_id:
                raise ValueError("Les deux équipes doivent être différentes.")

            user_team, _ = build_team(user_team_id)
            opponent_team, _ = build_team(opponent_team_id)

            rotation1 = {
                player["name"]: int(player["minutes"])
                for player in payload["rotation1"]
            }
            starter_names1 = [
                player["name"]
                for player in payload["rotation1"]
                if bool(player.get("starter"))
            ]
            role_map1 = None
            tactics1 = payload.get("tactics1", {})

            opponent_players = opponent_team.roster
            rotation2 = build_ai_rotation(opponent_team)
            starter_names2 = [player.name for player in opponent_team.starters]
            role_map2 = None
            tactics2 = ai_tactics(opponent_team, user_team)

            print()
            print("========================================")
            print(f"PLAN DE MATCH - {user_team.name}")
            print("========================================")
            print(f"Adversaire : {opponent_team.name}")
            print("5 majeur :", ", ".join(starter_names1))
            print("Minutes :")
            for name, minutes in rotation1.items():
                print(f"  {name} -> {minutes} min")
            print("Tactiques :", tactics1)
            print()
            print("Simulation en cours...")

            result = simulate_game(
                user_team,
                opponent_team,
                rotation1,
                rotation2,
                starter_names1,
                starter_names2,
                role_map1,
                role_map2,
                tactics1,
                tactics2,
            )

            print(
                "Match terminé :",
                result["team1"]["score"],
                "-",
                result["team2"]["score"],
            )

            self.send_json(
                200,
                {
                    "success": True,
                    "message": "Match terminé.",
                    "result": result,
                },
            )

        except Exception as error:
            print("❌ ERREUR :", error)
            self.send_json(400, {"success": False, "message": str(error)})


def main():
    server = ThreadingHTTPServer(("localhost", 8000), Server)
    server.daemon_threads = True

    print("========================================")
    print("NBA MANAGER V38 - SERVEUR")
    print("========================================")
    print()
    playable = [t for t in team_catalog() if t["playable"]]
    print(f"{len(playable)}/30 équipes jouables (effectif local complet).")
    print("Données joueurs : 2KRatings NBA 2K27")
    print("Ouvre : http://localhost:8000/NBA_MANAGER_INTERFACE/")
    print()
    server.serve_forever()


if __name__ == "__main__":
    main()
