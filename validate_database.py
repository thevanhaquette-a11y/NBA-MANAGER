import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA = BASE_DIR / 'data' / 'players_2k27.json'

CATEGORIES = ['outside_scoring','inside_scoring','athleticism','playmaking','defense','rebounding','stamina']

doc=json.loads(DATA.read_text(encoding='utf-8'))
players=doc.get('players',{})
print(f"Équipes dans le fichier : {len(players)}")
all_missing=[]
total=0
full=0
for team, roster in players.items():
    total += len(roster)
    team_full=0
    for p in roster:
        missing=[k for k in CATEGORIES if p.get(k) is None]
        if not missing:
            full += 1; team_full += 1
        else:
            all_missing.append((team,p.get('name'),missing))
    print(f"{team}: {len(roster)} joueurs | {team_full} complets")
print(f"Total joueurs : {total}")
print(f"7 catégories complètes : {full}")
print(f"Avec au moins une note manquante : {len(all_missing)}")
if all_missing:
    print('\nPremiers joueurs incomplets :')
    for team,name,missing in all_missing[:30]:
        print(f"- {team} | {name} | manque: {', '.join(missing)}")
