"""Tests + calibration du moteur.  Usage :  python test_engine.py [nb_matchs]

Vérifie la cohérence (box score, minutes, fautes, prolongations) et compare
les moyennes simulées aux ordres de grandeur NBA."""
import random
import statistics as st
import sys

import server
from main import DEFAULT_TACTICS, simulate_game

N = int(sys.argv[1]) if len(sys.argv) > 1 else 60
T1, T2 = "PHI", "SAS"

# Ordres de grandeur NBA (par équipe et par match)
NBA = {
    "points": (108, 118), "fg_pct": (45.0, 48.0), "three_attempted": (33, 40), "three_pct": (34.5, 37.5),
    "shots_attempted": (84, 92), "free_throws_attempted": (19, 26), "ft_pct": (76, 82),
    "rebounds": (41, 47), "assists": (23, 28), "turnovers": (12, 15.5), "fouls": (17, 21),
    "possessions": (94, 103),
}


def play_one(seed):
    random.seed(seed)
    a, _ = server.build_team(T1)
    b, _ = server.build_team(T2)
    starters, rot1 = server.build_auto_rotation_minutes(a)
    rot2 = server.build_ai_rotation(b)
    return simulate_game(a, b, rot1, rot2, [p.name for p in starters], [p.name for p in b.starters],
                         None, None, DEFAULT_TACTICS, server.ai_tactics(b, a))


def main():
    games = [play_one(i) for i in range(N)]
    errors = []

    for i, g in enumerate(games):
        for key in ("team1", "team2"):
            t = g[key]
            if sum(t["quarter_scores"]) != t["score"]:
                errors.append(f"match {i}: score par période ≠ score final ({key})")
            if len(t["quarter_scores"]) != g["periods"]:
                errors.append(f"match {i}: nombre de périodes incohérent ({key})")
            for p in t["players"]:
                if p["fouls"] > 6:
                    errors.append(f"match {i}: {p['name']} a {p['fouls']} fautes")
            expected_minutes = 240 + 25 * (g["periods"] - 4)
            if sum(p["minutes"] for p in t["players"]) != expected_minutes:
                errors.append(f"match {i}: minutes jouées {sum(p['minutes'] for p in t['players'])} ≠ {expected_minutes}")
        if g["team1"]["score"] == g["team2"]["score"]:
            errors.append(f"match {i}: égalité finale")

    print(f"{N} matchs {T1}-{T2}")
    print(f"{'stat':24s}{'moyenne':>9s}   plage NBA")
    for k, (lo, hi) in NBA.items():
        vals = [g[t]["score"] if k == "points" else g[t]["stats"][k] for g in games for t in ("team1", "team2")]
        m = st.mean(vals)
        flag = "" if lo <= m <= hi else "   <-- hors plage"
        print(f"{k:24s}{m:9.1f}   {lo}-{hi}{flag}")
    ot = sum(g["overtime"] for g in games)
    print(f"{'prolongations':24s}{ot:9d}   (~6 % des matchs NBA)")
    best = max(p["points"] for g in games for t in ("team1", "team2") for p in g[t]["players"])
    fouled_out = sum(1 for g in games for t in ("team1", "team2") for p in g[t]["players"] if p["fouls"] >= 6)
    print(f"{'max points (1 joueur)':24s}{best:9d}")
    print(f"{'exclusions 6 fautes':24s}{fouled_out:9d}")
    print()
    if errors:
        print("ERREURS :")
        for e in errors[:20]:
            print(" -", e)
        sys.exit(1)
    print("✅ Cohérence OK (box score, minutes, fautes, périodes)")


if __name__ == "__main__":
    main()
