import math
import random
from itertools import combinations, permutations


# =========================================================
# JOUEUR
# Les catégories générales sont basées sur les données
# affichées par 2KRatings (NBA 2K27).
# =========================================================


def infer_natural_role(position, overall, outside_scoring, inside_scoring, athleticism, playmaking, defense, rebounding, stamina):
    """Détermine le rôle naturel du joueur à partir de ses qualités.

    Le rôle est descriptif et automatique : il n'est jamais modifiable par le coach.
    Les tactiques déterminent ensuite l'utilisation du joueur pendant le match.
    """
    pos = (position or "SF").split("/")[0]

    # Créateur : priorité à la capacité à créer pour lui-même et pour les autres.
    if playmaking >= 85 and playmaking >= outside_scoring - 4:
        return "Créateur principal"
    if playmaking >= 76 and playmaking >= outside_scoring - 8:
        return "Créateur secondaire"

    # Gros profils intérieurs défensifs/rebondeurs.
    if pos in ("C", "PF"):
        if defense >= 82 and rebounding >= 75:
            return "Protecteur du cercle"
        if rebounding >= 78 and defense >= 68:
            return "Rebondeur"
        if inside_scoring >= 80:
            return "Scoreur intérieur"

    # 3&D : les deux qualités doivent être présentes, pas seulement le poste.
    if outside_scoring >= 70 and defense >= 70:
        return "3&D"

    # Spécialiste extérieur.
    if outside_scoring >= 83 and inside_scoring < 78 and playmaking < 76:
        return "Shooter"
    if outside_scoring >= 78 and athleticism >= 78:
        return "Scoreur extérieur"

    # Défenseur extérieur si la défense domine clairement son profil.
    if pos in ("PG", "SG", "SF") and defense >= 76 and defense >= outside_scoring - 2:
        return "Défenseur extérieur"

    if inside_scoring >= 78:
        return "Scoreur intérieur"
    if pos in ("C", "PF") and (rebounding >= 68 or defense >= 68):
        return "Intérieur"

    return "Scoreur extérieur"



class Player:
    def __init__(
        self,
        name,
        position,
        role,
        overall,
        outside_scoring,
        inside_scoring,
        athleticism,
        playmaking,
        defense,
        rebounding,
        stamina,
    ):
        self.name = name
        self.position = position
        self.role = infer_natural_role(
            position, overall, outside_scoring, inside_scoring, athleticism,
            playmaking, defense, rebounding, stamina
        )

        # Ratings généraux
        self.overall = overall
        self.outside_scoring = outside_scoring
        self.inside_scoring = inside_scoring
        self.athleticism = athleticism
        self.playmaking = playmaking
        self.defense = defense
        self.rebounding = rebounding
        self.stamina = stamina

        # Statistiques du match
        self.points = 0
        self.shots_made = 0
        self.shots_attempted = 0
        self.three_made = 0
        self.three_attempted = 0
        self.assists = 0
        self.rebounds = 0
        self.turnovers = 0
        self.fouls = 0
        self.deflections = 0
        self.contested_shots = 0
        self.free_throws_made = 0
        self.free_throws_attempted = 0
        self.minutes_played = 0
        self.fatigue = 0.0
        self._tendency_cache = None
        self.current_position = self.primary_position

    @property
    def primary_position(self):
        return self.position.split("/")[0]


# =========================================================
# EQUIPE
# =========================================================


class Team:
    def __init__(self, name, starters, bench):
        self.name = name
        self.roster = starters + bench
        self.starters = starters.copy()
        self.bench = bench.copy()
        self.on_court = starters.copy()
        self.rotation_plan = {}
        self.rotation_schedule = []
        self.matchups = {}

        # Mémoire de match : la défense apprend surtout des paniers réellement marqués.
        # Chaque entrée = (action, type de tir, zone, joueur, assisté).
        self.recent_shots = []
        self.recent_baskets = []


# =========================================================
# ROLES / TACTIQUES
# =========================================================

VALID_ROLES = [
    "Créateur principal",
    "Créateur secondaire",
    "Scoreur extérieur",
    "Scoreur intérieur",
    "Shooter",
    "3&D",
    "Défenseur extérieur",
    "Protecteur du cercle",
    "Rebondeur",
    "Intérieur",
    "Sixième homme",
]

DEFAULT_TACTICS = {
    # Offense
    "offenseStyle": "Équilibré",
    "tempo": "Normal",
    "threePointFocus": "Équilibré",
    "ballMovement": "Équilibré",
    "transitionOffense": "Équilibrée",
    "pickAndRollFrequency": "Normal",
    "postUpFrequency": "Normal",
    "driveFrequency": "Normal",
    "primaryOption": "Équilibrée",
    "shotSelection": "Normale",
    "offensiveRebound": "Normal",
    # Defense
    "defenseStyle": "Homme à homme",
    "pressure": "Normale",
    "helpDefense": "Normale",
    "pickAndRollCoverage": "Drop",
    "defensivePriority": "Équilibrée",
    "transitionDefense": "Équilibré",
    "defensiveRebound": "Équilibré",
    "foulAggression": "Normale",
}


ROLE_MODIFIERS = {
    "Créateur principal": {"playmaking": 8, "inside_scoring": 2},
    "Créateur secondaire": {"playmaking": 5, "outside_scoring": 2},
    "Scoreur extérieur": {"outside_scoring": 5},
    "Scoreur intérieur": {"inside_scoring": 7},
    "Shooter": {"outside_scoring": 7},
    "3&D": {"defense": 5, "outside_scoring": 4},
    "Défenseur extérieur": {"defense": 6},
    "Protecteur du cercle": {"defense": 7, "rebounding": 5},
    "Rebondeur": {"rebounding": 8},
    "Intérieur": {"inside_scoring": 3, "rebounding": 4},
    "Sixième homme": {"outside_scoring": 3, "inside_scoring": 3, "playmaking": 2},
}


# =========================================================
# TENDANCES INDIVIDUELLES
# =========================================================

# Les attributs généraux restent la base du joueur. Les tendances ne sont
# pas des ratings supplémentaires : elles décrivent la manière dont le joueur
# utilise ses qualités en match. Elles sont dérivées automatiquement pour
# donner des profils différents même à deux joueurs ayant des rôles proches.

ROLE_TENDENCY_BONUS = {
    "Créateur principal": {
        "usage": 10, "pick_and_roll_ballhandler": 18, "drive": 10,
        "isolation": 8, "pass": 10, "transition": 5,
    },
    "Créateur secondaire": {
        "usage": 4, "pick_and_roll_ballhandler": 10, "drive": 6,
        "pass": 8, "handoff": 5,
    },
    "Scoreur extérieur": {
        "usage": 7, "three": 7, "isolation": 6, "drive": 6,
        "midrange": 5,
    },
    "Scoreur intérieur": {
        "usage": 7, "post_up": 18, "paint": 14, "foul_draw": 10,
    },
    "Shooter": {
        "three": 18, "catch_and_shoot": 18, "handoff": 8,
    },
    "3&D": {
        "three": 10, "catch_and_shoot": 10,
    },
    "Défenseur extérieur": {
        "transition": 4,
    },
    "Protecteur du cercle": {
        "post_up": 5, "paint": 8,
    },
    "Rebondeur": {
        "post_up": 5, "paint": 7,
    },
    "Intérieur": {
        "post_up": 8, "paint": 8,
    },
    "Sixième homme": {
        "usage": 5, "isolation": 3, "drive": 4,
    },
}


# Tendances défensives : elles ne remplacent pas les ratings.
# Elles décrivent la façon dont chaque joueur utilise sa défense.
ROLE_DEFENSIVE_TENDENCY_BONUS = {
    "3&D": {"perimeter_pressure": 10, "closeout": 8, "switch": 8, "deny": 7, "help": 4},
    "Défenseur extérieur": {"perimeter_pressure": 13, "closeout": 10, "switch": 9, "deny": 10, "help": 4},
    "Protecteur du cercle": {"rim_protection": 15, "help": 12, "switch": -7, "closeout": 3},
    "Rebondeur": {"rim_protection": 5, "help": 4, "box_out": 10},
    "Intérieur": {"rim_protection": 5, "help": 6, "box_out": 7},
    "Créateur principal": {"perimeter_pressure": -2, "help": 2, "switch": 3},
    "Créateur secondaire": {"perimeter_pressure": -1, "help": 3, "switch": 4},
    "Scoreur extérieur": {"perimeter_pressure": 1, "help": 2},
}


def clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def build_tendency_profile(player):
    """Construit un profil de tendances 0-100 à partir des ratings + rôle."""
    if player._tendency_cache is not None:
        return player._tendency_cache

    role = ROLE_TENDENCY_BONUS.get(player.role, {})

    profile = {
        # Volume d'utilisation : scoring + création, modulés par le rôle.
        "usage": clamp(
            12
            + player.overall * 0.28
            + player.outside_scoring * 0.16
            + player.inside_scoring * 0.16
            + player.playmaking * 0.10
            + role.get("usage", 0)
        ),
        "three": clamp(
            8
            + player.outside_scoring * 0.55
            - player.inside_scoring * 0.10
            + role.get("three", 0)
            + (8 if player.primary_position in ["PG", "SG", "SF"] else -4)
        ),
        "midrange": clamp(
            22
            + player.outside_scoring * 0.28
            + player.inside_scoring * 0.12
            + player.athleticism * 0.06
            + role.get("midrange", 0)
        ),
        "paint": clamp(
            10
            + player.inside_scoring * 0.50
            + player.athleticism * 0.14
            + player.rebounding * 0.08
            + role.get("paint", 0)
            + (7 if player.primary_position in ["PF", "C"] else 0)
        ),
        "drive": clamp(
            10
            + player.athleticism * 0.32
            + player.inside_scoring * 0.22
            + player.playmaking * 0.10
            + role.get("drive", 0)
            + (5 if player.primary_position in ["PG", "SG", "SF"] else -3)
        ),
        "post_up": clamp(
            4
            + player.inside_scoring * 0.38
            + player.rebounding * 0.14
            + player.athleticism * 0.05
            + role.get("post_up", 0)
            + (9 if player.primary_position in ["PF", "C"] else -2)
        ),
        "isolation": clamp(
            8
            + player.outside_scoring * 0.17
            + player.inside_scoring * 0.17
            + player.athleticism * 0.18
            + player.playmaking * 0.12
            + role.get("isolation", 0)
        ),
        "pick_and_roll_ballhandler": clamp(
            8
            + player.playmaking * 0.52
            + player.athleticism * 0.22
            + player.outside_scoring * 0.08
            + role.get("pick_and_roll_ballhandler", 0)
        ),
        "pick_and_roll_screener": clamp(
            6
            + player.inside_scoring * 0.30
            + player.rebounding * 0.30
            + player.athleticism * 0.15
            + role.get("pick_and_roll_screener", 0)
            + (10 if player.primary_position in ["PF", "C"] else 0)
        ),
        "catch_and_shoot": clamp(
            8
            + player.outside_scoring * 0.62
            + player.playmaking * 0.05
            + role.get("catch_and_shoot", 0)
        ),
        "handoff": clamp(
            8
            + player.outside_scoring * 0.30
            + player.athleticism * 0.17
            + player.playmaking * 0.12
            + role.get("handoff", 0)
        ),
        "pass": clamp(
            8
            + player.playmaking * 0.72
            + player.overall * 0.08
            + role.get("pass", 0)
        ),
        "transition": clamp(
            8
            + player.athleticism * 0.42
            + player.inside_scoring * 0.16
            + player.outside_scoring * 0.10
            + player.stamina * 0.08
            + role.get("transition", 0)
        ),
        # Tendances défensives individuelles.
        "perimeter_pressure": clamp(
            8
            + player.defense * 0.52
            + player.athleticism * 0.27
            + player.stamina * 0.08
            + ROLE_DEFENSIVE_TENDENCY_BONUS.get(player.role, {}).get("perimeter_pressure", 0)
        ),
        "closeout": clamp(
            8
            + player.defense * 0.44
            + player.athleticism * 0.34
            + player.stamina * 0.06
            + ROLE_DEFENSIVE_TENDENCY_BONUS.get(player.role, {}).get("closeout", 0)
        ),
        "deny": clamp(
            8
            + player.defense * 0.43
            + player.athleticism * 0.23
            + player.playmaking * 0.09
            + ROLE_DEFENSIVE_TENDENCY_BONUS.get(player.role, {}).get("deny", 0)
        ),
        "help": clamp(
            8
            + player.defense * 0.33
            + player.rebounding * 0.21
            + player.athleticism * 0.14
            + ROLE_DEFENSIVE_TENDENCY_BONUS.get(player.role, {}).get("help", 0)
        ),
        "rim_protection": clamp(
            6
            + player.defense * 0.42
            + player.rebounding * 0.24
            + player.athleticism * 0.15
            + (10 if player.primary_position in ["PF", "C"] else -2)
            + ROLE_DEFENSIVE_TENDENCY_BONUS.get(player.role, {}).get("rim_protection", 0)
        ),
        "switch": clamp(
            20
            + player.defense * 0.24
            + player.athleticism * 0.45
            + player.stamina * 0.06
            + ROLE_DEFENSIVE_TENDENCY_BONUS.get(player.role, {}).get("switch", 0)
        ),
        "box_out": clamp(
            10
            + player.rebounding * 0.57
            + player.defense * 0.18
            + ROLE_DEFENSIVE_TENDENCY_BONUS.get(player.role, {}).get("box_out", 0)
        ),
        "foul_draw": clamp(
            6
            + player.inside_scoring * 0.34
            + player.athleticism * 0.18
            + player.overall * 0.08
            + role.get("foul_draw", 0)
        ),
    }

    # Cohérence interne : un joueur très porté sur le tir extérieur ne doit
    # pas devenir subitement très intérieur sans que ses qualités le justifient.
    profile["three"] = clamp(profile["three"] + (profile["catch_and_shoot"] - 60) * 0.12)
    profile["paint"] = clamp(profile["paint"] + (profile["post_up"] - 60) * 0.10)
    player._tendency_cache = profile
    return profile


def tendency(player, key):
    return build_tendency_profile(player).get(key, 50.0)



def build_default_rotation_minutes(players, starters):
    """Crée une rotation par défaut sur tout l'effectif.

    Les titulaires reçoivent 30 min chacun. Les 90 minutes restantes sont
    réparties entre tous les remplaçants, de façon à ce que chaque joueur
    de l'effectif soit pris en compte et que le total fasse exactement 240.
    """
    minutes = {p.name: 0 for p in players}
    for p in starters:
        minutes[p.name] = 30
    starter_names = {p.name for p in starters}
    bench = sorted([p for p in players if p.name not in starter_names],
                   key=lambda p: p.overall, reverse=True)
    if bench:
        base = 90 // len(bench)
        remainder = 90 % len(bench)
        for i, p in enumerate(bench):
            minutes[p.name] = base + (1 if i < remainder else 0)
    return minutes


# =========================================================
# MOTEUR V21 - architecture tactique centralisée
# =========================================================

REQUIRED_POSITIONS = ("PG", "SG", "SF", "PF", "C")
GAME_MINUTES = 48
GAME_SECONDS = GAME_MINUTES * 60
OT_MINUTES = 5


# Toutes les décisions tactiques modifiables dans l'interface sont centralisées
# ici. Les valeurs représentent des tendances relatives et non des bonus directs
# au score : elles modifient le comportement qui mène ensuite au résultat.
TACTIC_EFFECTS = {
    "offenseStyle": {
        "Équilibré": {},
        "Pace & Space": {"transition": 0.75, "pick_and_roll": 0.45, "catch_and_shoot": 0.70, "post_up": -0.45},
        "Jeu intérieur": {"post_up": 0.95, "drive": 0.45, "pick_and_roll": 0.30, "catch_and_shoot": -0.55},
        "Adresse extérieure": {"catch_and_shoot": 0.90, "handoff": 0.45, "pick_and_roll": 0.30, "post_up": -0.55},
        "Motion": {"handoff": 0.80, "catch_and_shoot": 0.55, "pick_and_roll": 0.25, "isolation": -0.65},
        "Isolation": {"isolation": 1.10, "drive": 0.50, "handoff": -0.40, "catch_and_shoot": -0.35},
    },
    "tempo": {
        "Lent": {"post_up": 0.20, "isolation": 0.15, "transition": -0.45},
        "Normal": {},
        "Rapide": {"transition": 0.75, "drive": 0.30, "post_up": -0.20},
    },
    "threePointFocus": {
        "Limité": {"catch_and_shoot": -0.65, "handoff": -0.15, "drive": 0.25, "post_up": 0.25},
        "Équilibré": {},
        "Accentué": {"catch_and_shoot": 0.75, "handoff": 0.25, "pick_and_roll": 0.20, "drive": -0.10},
    },
    "ballMovement": {
        "Statique": {"isolation": 0.35, "post_up": 0.10, "handoff": -0.25},
        "Équilibré": {},
        "Très collectif": {"handoff": 0.45, "catch_and_shoot": 0.35, "pick_and_roll": 0.25, "isolation": -0.45},
    },
    "transitionOffense": {
        "Repli": {"transition": -0.70},
        "Équilibrée": {},
        "Agressive": {"transition": 0.95, "drive": 0.20},
    },
    "pickAndRollFrequency": {
        "Rare": {"pick_and_roll": -0.75},
        "Normal": {},
        "Fréquent": {"pick_and_roll": 0.85},
    },
    "postUpFrequency": {
        "Rare": {"post_up": -0.75},
        "Normal": {},
        "Fréquent": {"post_up": 0.85},
    },
    "driveFrequency": {
        "Rare": {"drive": -0.70},
        "Normal": {},
        "Fréquent": {"drive": 0.80},
    },
    "shotSelection": {
        "Sélective": {"isolation": -0.25, "drive": -0.15, "catch_and_shoot": 0.10},
        "Normale": {},
        "Agressive": {"isolation": 0.30, "drive": 0.30, "transition": 0.10},
    },
}

DEFENSE_EFFECTS = {
    "defenseStyle": {
        "Homme à homme": {"man": 1.0},
        "Zone": {"zone": 1.0},
        "Agressive": {"pressure": 1.0, "foul_risk": 1.0},
        "Repli rapide": {"transition_stop": 1.0, "halfcourt": -0.15},
    },
    "pressure": {
        "Faible": {"perimeter": -0.30, "turnover": -0.25},
        "Normale": {},
        "Forte": {"perimeter": 0.50, "turnover": 0.45, "foul_risk": 0.25},
    },
    "helpDefense": {
        "Faible": {"paint": -0.25, "kickout": 0.05},
        "Normale": {},
        "Forte": {"paint": 0.60, "kickout": 0.65, "rotation": 0.40},
    },
    "pickAndRollCoverage": {
        "Drop": {"paint": 0.35, "perimeter": -0.25},
        "Switch": {"switch": 0.75, "mismatch_risk": 0.20},
        "Hedge": {"perimeter": 0.25, "foul_risk": 0.18, "rotation": 0.30},
    },
    "defensivePriority": {
        "Équilibrée": {},
        "Limiter 3 pts": {"perimeter": 0.55, "paint": -0.28, "kickout": -0.25},
        "Protéger peinture": {"paint": 0.65, "perimeter": -0.35, "drive": -0.20},
    },
    "transitionDefense": {
        "Équilibré": {},
        "Repli rapide": {"transition": 0.75, "offensive_rebound": -0.20},
        "Crash offensif autorisé": {"transition": -0.55, "offensive_rebound": 0.25},
    },
    "defensiveRebound": {
        "Équilibré": {},
        "Sécuriser": {"def_rebound": 0.65, "transition_allowed": -0.15},
        "Agressif": {"def_rebound": 0.25, "transition_allowed": 0.15},
    },
    "foulAggression": {
        "Disciplinée": {"foul_risk": -0.45, "contest": -0.08},
        "Normale": {},
        "Agressive": {"foul_risk": 0.55, "contest": 0.18, "turnover": 0.15},
    },
}


class TacticalModel:
    """Interprète toutes les consignes du coach au même endroit."""
    ACTIONS = ("transition", "pick_and_roll", "isolation", "post_up", "handoff", "catch_and_shoot", "drive")

    def __init__(self, tactics):
        self.tactics = normalize_tactics(tactics)
        self.action_bias = {action: 0.0 for action in self.ACTIONS}
        for key, table in TACTIC_EFFECTS.items():
            choice = self.tactics.get(key)
            for action, delta in table.get(choice, {}).items():
                if action in self.action_bias:
                    self.action_bias[action] += delta

        self.defense = {
            "perimeter": 0.0, "paint": 0.0, "turnover": 0.0, "kickout": 0.0,
            "rotation": 0.0, "switch": 0.0, "mismatch_risk": 0.0, "foul_risk": 0.0,
            "pressure": 0.0,
            "contest": 0.0, "transition": 0.0, "def_rebound": 0.0,
            "offensive_rebound": 0.0, "transition_allowed": 0.0, "drive": 0.0,
            "man": 0.0, "zone": 0.0, "transition_stop": 0.0, "halfcourt": 0.0
        }
        for key, table in DEFENSE_EFFECTS.items():
            choice = self.tactics.get(key)
            for metric, delta in table.get(choice, {}).items():
                self.defense[metric] += delta

        self.pass_bonus = {
            "Statique": -0.10,
            "Équilibré": 0.0,
            "Très collectif": 0.22,
        }.get(self.tactics.get("ballMovement"), 0.0)
        self.shot_risk = {
            "Sélective": -0.15,
            "Normale": 0.0,
            "Agressive": 0.18,
        }.get(self.tactics.get("shotSelection"), 0.0)

    def action_weight(self, action):
        return max(0.08, 1.0 + self.action_bias.get(action, 0.0))

    def is_zone(self):
        return self.tactics.get("defenseStyle") == "Zone"


# =========================================================
# UTILS / ROTATIONS
# =========================================================


def get_all_players(team):
    return team.roster


def normalize_tactics(tactics):
    result = DEFAULT_TACTICS.copy()
    if isinstance(tactics, dict):
        result.update({key: value for key, value in tactics.items() if key in result})
    return result


def eligible_positions(player):
    return tuple(position.strip() for position in player.position.split("/"))


def primary_position(player):
    return player.position.split("/")[0]


def position_index(player):
    position = getattr(player, "current_position", primary_position(player))
    return {"PG": 1, "SG": 2, "SF": 3, "PF": 4, "C": 5}.get(position, 3)


def position_assignment(lineup):
    """Retourne une affectation unique PG/SG/SF/PF/C pour cinq joueurs."""
    if len(lineup) != 5 or len({p.name for p in lineup}) != 5:
        return None

    required = list(REQUIRED_POSITIONS)
    candidates = {
        pos: [p for p in lineup if pos in eligible_positions(p)]
        for pos in required
    }
    if any(not candidates[pos] for pos in required):
        return None

    # On commence par les postes les plus rares dans ce cinq.
    order = sorted(required, key=lambda pos: len(candidates[pos]))
    best = None
    best_score = float('-inf')

    def search(index, used, mapping, score):
        nonlocal best, best_score
        if index == len(order):
            if score > best_score:
                best_score = score
                best = dict(mapping)
            return
        pos = order[index]
        for player in sorted(candidates[pos], key=lambda p: p.overall, reverse=True):
            if player.name in used:
                continue
            # Bonus quand le poste correspond à sa position principale.
            add = 100 if primary_position(player) == pos else 75
            used.add(player.name)
            mapping[pos] = player
            search(index + 1, used, mapping, score + add + player.overall * 0.01)
            used.remove(player.name)
            mapping.pop(pos, None)

    search(0, set(), {}, 0.0)
    return best



class _FlowEdge:
    __slots__ = ("to", "rev", "cap")
    def __init__(self, to, rev, cap):
        self.to = to
        self.rev = rev
        self.cap = cap


class _Dinic:
    """Petit max-flow local, suffisant pour les 240 créneaux d'un match."""
    def __init__(self, n):
        self.g = [[] for _ in range(n)]
        self.level = [-1] * n
        self.it = [0] * n

    def add_edge(self, u, v, cap):
        fwd = _FlowEdge(v, len(self.g[v]), cap)
        rev = _FlowEdge(u, len(self.g[u]), 0)
        self.g[u].append(fwd)
        self.g[v].append(rev)
        return len(self.g[u]) - 1

    def bfs(self, s, t):
        from collections import deque
        self.level = [-1] * len(self.g)
        q = deque([s])
        self.level[s] = 0
        while q:
            u = q.popleft()
            for e in self.g[u]:
                if e.cap > 0 and self.level[e.to] < 0:
                    self.level[e.to] = self.level[u] + 1
                    q.append(e.to)
        return self.level[t] >= 0

    def dfs(self, u, t, f):
        if u == t:
            return f
        for i in range(self.it[u], len(self.g[u])):
            self.it[u] = i
            e = self.g[u][i]
            if e.cap > 0 and self.level[u] + 1 == self.level[e.to]:
                pushed = self.dfs(e.to, t, min(f, e.cap))
                if pushed:
                    e.cap -= pushed
                    self.g[e.to][e.rev].cap += pushed
                    return pushed
            self.it[u] += 1
        return 0

    def max_flow(self, s, t):
        total = 0
        INF = 10**9
        while self.bfs(s, t):
            self.it = [0] * len(self.g)
            while True:
                pushed = self.dfs(s, t, INF)
                if not pushed:
                    break
                total += pushed
        return total


def build_feasible_rotation(team):
    """Construit exactement 48 cinq-majeurs en respectant toutes les minutes.

    Modèle :
      joueur -> (joueur, minute) -> poste/minute.
    Le nœud (joueur, minute) a une capacité de 1 : un joueur ne peut donc pas
    occuper deux postes pendant la même minute. Chaque poste de chaque minute
    a aussi une capacité de 1. Le flot total doit être exactement 240.
    """
    players = list(team.roster)
    by_name = {p.name: p for p in players}
    target = {p.name: int(team.rotation_plan.get(p.name, 0)) for p in players}

    starter_lineup = list(team.starters)
    starter_assignment = position_assignment(starter_lineup)
    if starter_assignment is None:
        raise ValueError("Le cinq majeur doit couvrir PG, SG, SF, PF et C.")
    if any(target.get(p.name, 0) <= 0 for p in starter_lineup):
        raise ValueError("Un titulaire doit avoir au moins 1 minute.")
    if sum(target.values()) != 240:
        raise ValueError("Le total doit être de 240 minutes.")

    active = [p for p in players if target[p.name] > 0]
    if len(active) < 5:
        raise ValueError("Il faut au moins 5 joueurs avec des minutes positives.")

    # Test rapide de capacité par poste : nécessaire mais pas suffisant.
    for pos in REQUIRED_POSITIONS:
        capacity = sum(target[p.name] for p in active if pos in eligible_positions(p))
        if capacity < 48:
            raise ValueError(f"Poste {pos} impossible : capacité {capacity}/48 minutes avec les minutes indiquées.")

    # Nœuds du flot.
    # S -> joueur (capacité = minutes cibles)
    # joueur -> joueur/minute (1)
    # joueur/minute -> minute/poste (1 si joueur éligible)
    # minute/poste -> T (1)
    slot_count = 48 * 5
    player_min_count = len(active) * 48
    n = 2 + len(active) + player_min_count + slot_count
    source = 0
    sink = n - 1
    flow = _Dinic(n)

    player_node = {}
    player_min_node = {}
    slot_node = {}
    edge_refs = {}

    next_node = 1
    for p in active:
        player_node[p.name] = next_node
        next_node += 1
    for p in active:
        for minute in range(48):
            player_min_node[(p.name, minute)] = next_node
            next_node += 1
    for minute in range(48):
        for pos_index, pos in enumerate(REQUIRED_POSITIONS):
            slot_node[(minute, pos)] = next_node
            next_node += 1

    for p in active:
        flow.add_edge(source, player_node[p.name], target[p.name])
        eligible = set(eligible_positions(p))
        for minute in range(48):
            pm = player_min_node[(p.name, minute)]
            flow.add_edge(player_node[p.name], pm, 1)
            for pos in REQUIRED_POSITIONS:
                if pos in eligible:
                    edge_index = flow.add_edge(pm, slot_node[(minute, pos)], 1)
                    edge_refs[(p.name, minute, pos)] = (pm, edge_index)

    for minute in range(48):
        for pos in REQUIRED_POSITIONS:
            flow.add_edge(slot_node[(minute, pos)], sink, 1)

    total = flow.max_flow(source, sink)
    if total != 240:
        raise ValueError("Impossible de construire une rotation exacte : ces minutes ne permettent pas de remplir PG, SG, SF, PF et C pendant les 48 minutes.")

    # Reconstitue le cinq de chaque minute à partir des arcs saturés.
    minute_assignments = []
    for minute in range(48):
        assignment = {}
        lineup = []
        for pos in REQUIRED_POSITIONS:
            found = None
            for p in active:
                ref = edge_refs.get((p.name, minute, pos))
                if ref is None:
                    continue
                pm, edge_index = ref
                edge = flow.g[pm][edge_index]
                # capacité initiale = 1 ; capacité résiduelle 0 => flot utilisé.
                if edge.cap == 0:
                    found = p
                    break
            if found is None:
                raise ValueError(f"Erreur interne de reconstruction de la rotation à la minute {minute + 1} ({pos}).")
            assignment[pos] = found
            lineup.append(found)
        if len({p.name for p in lineup}) != 5:
            raise ValueError(f"Erreur interne : un joueur occupe deux postes à la minute {minute + 1}.")
        minute_assignments.append((lineup, assignment))

    # Regroupe les compositions identiques et place les compositions les plus
    # proches côte à côte. Cela donne une vraie logique de rotations sans
    # modifier les minutes cibles.
    remaining = minute_assignments[:]
    ordered = []

    def names(items):
        return {p.name for p in items}

    starter_names = names(starter_lineup)
    start_index = next((i for i, (lu, _) in enumerate(remaining) if names(lu) == starter_names), 0)
    ordered.append(remaining.pop(start_index))
    while remaining:
        previous = names(ordered[-1][0])
        best_index = 0
        best_key = None
        for i, (lu, assignment) in enumerate(remaining):
            current = names(lu)
            overlap = len(previous & current)
            starters = len(starter_names & current)
            # Préfère 4/5 joueurs conservés, puis une composition avec le plus
            # de titulaires raisonnable, puis l'OVR.
            ovr = sum(p.overall for p in lu)
            key = (overlap, starters, ovr)
            if best_key is None or key > best_key:
                best_key = key
                best_index = i
        ordered.append(remaining.pop(best_index))

    schedule = [lineup for lineup, _ in ordered]
    assignments = [assignment for _, assignment in ordered]
    return schedule, assignments

def configure_team_for_match(team, starter_names=None, role_map=None):
    if starter_names is None:
        starter_names = [p.name for p in team.starters]
    by_name = {p.name: p for p in team.roster}
    if len(starter_names) != 5 or len(set(starter_names)) != 5:
        raise ValueError("Il faut exactement 5 joueurs titulaires.")
    if any(name not in by_name for name in starter_names):
        raise ValueError("Un joueur du cinq majeur est inconnu.")
    # Les rôles sont calculés automatiquement depuis les ratings.
    # role_map est conservé dans la signature pour compatibilité avec les anciennes versions,
    # mais il n'est volontairement plus utilisé.
    for p in team.roster:
        p.role = infer_natural_role(
            p.position, p.overall, p.outside_scoring, p.inside_scoring,
            p.athleticism, p.playmaking, p.defense, p.rebounding, p.stamina
        )
        p._tendency_cache = None
    team.starters = [by_name[n] for n in starter_names]
    team.bench = [p for p in team.roster if p.name not in set(starter_names)]
    team.on_court = team.starters.copy()
    if position_assignment(team.starters) is None:
        raise ValueError("Le cinq majeur doit couvrir PG, SG, SF, PF et C.")
    team.starting_position_assignment = position_assignment(team.starters)


def set_rotation_plan(team, rotation_plan):
    names = {p.name for p in team.roster}
    if set(rotation_plan) != names:
        raise ValueError("Le plan de rotation ne correspond pas à l'effectif.")
    for mins in rotation_plan.values():
        if not isinstance(mins, int) or mins < 0 or mins > 48:
            raise ValueError("Chaque joueur doit avoir entre 0 et 48 minutes.")
    if sum(rotation_plan.values()) != 240:
        raise ValueError("Le total doit être de 240 minutes.")
    if any(rotation_plan[p.name] <= 0 for p in team.starters):
        raise ValueError("Un titulaire doit avoir au moins 1 minute.")
    team.rotation_plan = rotation_plan.copy()
    team.rotation_schedule, team.rotation_position_schedule = build_feasible_rotation(team)


def emergency_lineup_for_position(team, required_position, scheduled_lineup):
    """Remplacement exceptionnel si un joueur est indisponible (6 fautes).
    On privilégie un joueur du banc qui peut couvrir le poste et qui a encore une
    bonne quantité de minutes-cible non jouées. Cela n'arrive qu'en cas exceptionnel.
    """
    candidates = [p for p in team.roster if p not in scheduled_lineup and p.fouls < 6 and required_position in eligible_positions(p)]
    if not candidates:
        candidates = [p for p in team.roster if p not in scheduled_lineup and p.fouls < 6]
    return max(candidates, key=lambda p: (team.rotation_plan[p.name] - p.minutes_played, p.overall), default=None)


def apply_rotation_for_minute(team, minute_index):
    desired = list(team.rotation_schedule[min(minute_index, 47)])
    # Si un joueur prévu est disqualifié, on le remplace sur son poste.
    for pos, player in list(team.rotation_position_schedule[min(minute_index, 47)].items()):
        if player.fouls >= 6:
            replacement = emergency_lineup_for_position(team, pos, desired)
            if replacement is not None:
                desired.remove(player); desired.append(replacement)
    assignment = position_assignment(desired)
    if assignment is None:
        # Dernier filet de sécurité : conserver la lineup planifiée si aucune solution.
        desired = [p for p in team.rotation_schedule[min(minute_index, 47)] if p.fouls < 6]
        for pos in REQUIRED_POSITIONS:
            if len(desired) >= 5: break
            candidate = emergency_lineup_for_position(team, pos, desired)
            if candidate and candidate not in desired: desired.append(candidate)
        assignment = position_assignment(desired)
    if assignment is None:
        # Aucun cinq ne couvre PG/SG/SF/PF/C après les exclusions : on joue avec les meilleurs
        # joueurs disponibles, sans exigence de poste, plutôt que d'interrompre le match.
        set_overtime_lineup(team)
        return
    team.on_court = desired
    team.bench = [p for p in team.roster if p not in desired]
    for pos, player in assignment.items():
        player.current_position = pos


def reset_game_stats(team):
    for p in team.roster:
        p.points = p.shots_made = p.shots_attempted = 0
        p.three_made = p.three_attempted = p.assists = p.rebounds = 0
        p.turnovers = p.fouls = p.deflections = p.contested_shots = 0
        p.free_throws_made = p.free_throws_attempted = 0
        p.minutes_played = 0
        p.fatigue = 0.0
        p.current_position = primary_position(p)
    team.on_court = team.starters.copy(); team.bench = [p for p in team.roster if p not in team.on_court]
    team.recent_shots = []; team.recent_baskets = []
    team._points_in_paint = 0
    team._possessions = 0


# =========================================================
# STATS EFFECTIVES / TENDANCES
# =========================================================


def frequency_multiplier(value):
    return {"Rare": 0.55, "Normal": 1.0, "Fréquent": 1.60}.get(value, 1.0)


def role_bonus(player, stat):
    return ROLE_MODIFIERS.get(player.role, {}).get(stat, 0)


def effective_stat(player, stat):
    return getattr(player, stat) + role_bonus(player, stat)


def stat_with_fatigue(player, stat):
    # La fatigue érode progressivement les performances techniques, sans toucher
    # aux ratings de base affichés à l'utilisateur.
    value = effective_stat(player, stat)
    fatigue_factor = 1.0 - (player.fatigue * 0.0038)
    return max(1.0, value * max(0.72, fatigue_factor))


def update_fatigue(player):
    gain = 0.62 + (100 - player.stamina) * 0.014
    if player.current_position in ("PG", "SG"):
        gain += 0.04
    player.fatigue = min(100.0, player.fatigue + gain)


def recover_fatigue(player):
    player.fatigue = max(0.0, player.fatigue - 2.4)


# =========================================================
# DÉFENSE : rating spécialisé + matchups / zone
# =========================================================


def perimeter_defense(player):
    value = player.defense * 0.70 + player.athleticism * 0.30
    pos = primary_position(player)
    if pos in ("PG", "SG", "SF"): value += 2
    if pos == "C": value -= 4
    if player.role == "Défenseur extérieur": value += 6
    if player.role == "3&D": value += 3
    return max(1.0, min(99.0, value))


def interior_defense(player):
    value = player.defense * 0.74 + player.rebounding * 0.26
    pos = primary_position(player)
    if pos in ("PF", "C"): value += 3
    if pos == "PG": value -= 3
    if player.role == "Protecteur du cercle": value += 8
    if player.role in ("Intérieur", "Rebondeur"): value += 3
    return max(1.0, min(99.0, value))


def defender_quality(defender, shot_area, tactics, attacker=None):
    model = TacticalModel(tactics)
    p = perimeter_defense(defender) * (1 - defender.fatigue / 180)
    i = interior_defense(defender) * (1 - defender.fatigue / 180)
    if shot_area == "paint":
        value = i + tendency(defender, "rim_protection") * 0.08
        value += model.defense["paint"] * 5
    elif shot_area == "midrange":
        value = p * 0.60 + i * 0.40
        value += model.defense["perimeter"] * 3
    else:
        value = p + tendency(defender, "closeout") * 0.08
        value += model.defense["perimeter"] * 5
    value += tendency(defender, "help") * 0.025 if shot_area == "paint" else 0
    if model.tactics.get("pressure") == "Forte": value += 3
    if model.tactics.get("pressure") == "Faible": value -= 2
    value += model.defense["contest"] * 8.0
    if attacker is not None:
        gap = abs(position_index(defender) - position_index(attacker))
        value -= gap * (2.4 if shot_area == "paint" else 3.0)
        if gap >= 2:
            value += max(0, tendency(defender, "switch") - 60) * 0.05
    return max(10.0, value)


def defender_suitability(defender, attacker, shot_area="perimeter"):
    return defender_quality(defender, shot_area, DEFAULT_TACTICS, attacker)


def build_defensive_matchups(attacking_team, defending_team, tactics):
    attackers = list(attacking_team.on_court); defenders = list(defending_team.on_court)
    best = None; best_score = float("-inf")
    for perm in permutations(defenders):
        score = 0.0
        for a, d in zip(attackers, perm):
            likely = "paint" if primary_position(a) in ("PF", "C") else "perimeter"
            score += defender_quality(d, likely, tactics, a)
        if score > best_score:
            best_score = score; best = perm
    defending_team.matchups = {a.name: d.name for a, d in zip(attackers, best)}


def man_matchup_defender(defending_team, attacker):
    name = defending_team.matchups.get(attacker.name)
    if name:
        for d in defending_team.on_court:
            if d.name == name: return d
    return max(defending_team.on_court, key=lambda d: defender_quality(d, "perimeter", DEFAULT_TACTICS, attacker))


def zone_defender(defending_team, attacker, shot_area, tactics):
    # Une zone affecte une responsabilité de zone, pas une paire fixe attaquant/défenseur.
    candidates = list(defending_team.on_court)
    if shot_area == "paint":
        return max(candidates, key=lambda d: defender_quality(d, "paint", tactics, attacker) + tendency(d, "rim_protection") * 0.12)
    if shot_area == "midrange":
        return max(candidates, key=lambda d: defender_quality(d, "midrange", tactics, attacker) + tendency(d, "help") * 0.08)
    return max(candidates, key=lambda d: defender_quality(d, "perimeter", tactics, attacker) + tendency(d, "closeout") * 0.12)


def get_matchup_defender(defending_team, attacker, shot_area=None, tactics=None):
    tactics = normalize_tactics(tactics)
    if tactics.get("defenseStyle") == "Zone" and shot_area:
        return zone_defender(defending_team, attacker, shot_area, tactics)
    return man_matchup_defender(defending_team, attacker)


def get_help_defender(defending_team, primary_defender, attacker, shot_area, tactics):
    model = TacticalModel(tactics)
    candidates = [p for p in defending_team.on_court if p != primary_defender]
    if not candidates or tactics.get("helpDefense") == "Faible":
        return None
    chance = 0.20 + model.defense["rotation"] * 0.10
    if shot_area == "paint": chance += 0.30
    chance += max(-0.08, min(0.20, model.defense["paint"] * 0.12))
    if tactics.get("defensivePriority") == "Protéger peinture" and shot_area == "paint": chance += 0.12
    if tactics.get("defensivePriority") == "Limiter 3 pts" and shot_area == "perimeter": chance += 0.10
    chance += (tendency(max(candidates, key=lambda x: tendency(x, "help")), "help") - 50) * 0.002
    if random.random() >= min(0.92, chance): return None
    if shot_area == "paint":
        return max(candidates, key=lambda p: interior_defense(p) + tendency(p, "help") * 0.20)
    return max(candidates, key=lambda p: perimeter_defense(p) + tendency(p, "closeout") * 0.20)


def pick_and_roll_defenders(defending_team, ballhandler, screener, primary_defender, tactics):
    coverage = tactics.get("pickAndRollCoverage", "Drop")
    model = TacticalModel(tactics)
    if model.is_zone():
        return zone_defender(defending_team, ballhandler, "perimeter", tactics), None
    screener_def = man_matchup_defender(defending_team, screener) if screener else None
    if coverage == "Switch" and screener_def:
        return screener_def, None
    if coverage == "Hedge" and screener_def:
        return primary_defender, screener_def
    # Drop : porteur reste avec son défenseur, le grand reste bas comme aide intérieure.
    return primary_defender, screener_def if screener_def and random.random() < 0.45 else None


# =========================================================
# ADAPTATION PAR LES PANIERS MARQUÉS
# =========================================================


def record_success(team, action, shot_type, shot_area, player, assisted):
    team.recent_baskets.append({"action": action, "shot_type": shot_type, "area": shot_area,
                                "player": player.name, "assisted": assisted})
    if len(team.recent_baskets) > 10: team.recent_baskets.pop(0)


def record_attempt(team, action, shot_type, shot_area):
    team.recent_shots.append((action, shot_type, shot_area))
    if len(team.recent_shots) > 10: team.recent_shots.pop(0)


def adaptation_strength(attacking_team, action, shot_type, shot_area):
    history = attacking_team.recent_baskets[-8:]
    if not history: return 0.0
    value = 0.0
    for idx, basket in enumerate(reversed(history)):
        recency = 1.0 - idx * 0.10
        if basket["action"] == action: value += 1.30 * recency
        if basket["shot_type"] == shot_type: value += 0.55 * recency
        if basket["area"] == shot_area: value += 0.40 * recency
    return min(9.0, value)


def adaptive_action_weights(team):
    # Si une même solution vient de fonctionner, elle reste exploitable mais
    # perd un peu de priorité : le coach adverse commence à fermer cette solution.
    weights = {a: 1.0 for a in TacticalModel.ACTIONS}
    recent = team.recent_baskets[-5:]
    for b in recent:
        if b["action"] in weights:
            weights[b["action"]] *= 0.92
    return weights


# =========================================================
# OFFENSE : décisions individuelles + tactiques
# =========================================================


def weighted_pick(items, scores, temperature=6.0):
    """Tirage pondéré (softmax) : le meilleur profil est favori, sans être systématique."""
    top = max(scores)
    weights = [math.exp((sc - top) / temperature) for sc in scores]
    return random.choices(items, weights=weights, k=1)[0]


def primary_option_bonus(player, tactics):
    option = tactics.get("primaryOption", "Équilibrée")
    if option == "Meilleur scoreur":
        return max(0.0, max(player.outside_scoring, player.inside_scoring) - 60) * 0.35
    if option == "Créateur principal":
        return max(0.0, player.playmaking - 60) * 0.35 + (6 if player.role == "Créateur principal" else 0)
    if option == "Jeu intérieur":
        return max(0.0, player.inside_scoring - 60) * 0.35 + (6 if primary_position(player) in ("PF", "C") else 0)
    return 0.0


def transition_stop_value(model):
    """Capacité de la défense à stopper la transition (négatif = elle la facilite)."""
    d = model.defense
    return d["transition"] + 0.75 * d["transition_stop"] - d["transition_allowed"]


def choose_offensive_action(team, tactics, score_for=0, score_against=0, clock_remaining=0, defending_tactics=None):
    model = TacticalModel(tactics); weights = {a: 1.0 for a in model.ACTIONS}
    for a in weights: weights[a] *= model.action_weight(a)

    # L'utilisateur fixe le style ; les profils des joueurs décident comment ce style est exécuté.
    avg = {k: sum(tendency(p, k) for p in team.on_court) / 5 for k in [
        "transition", "pick_and_roll_ballhandler", "post_up", "handoff", "catch_and_shoot", "drive", "isolation"
    ]}
    weights["transition"] *= 1 + (avg["transition"] - 55) / 260
    weights["pick_and_roll"] *= 1 + (avg["pick_and_roll_ballhandler"] - 55) / 230
    weights["post_up"] *= 1 + (avg["post_up"] - 55) / 230
    weights["handoff"] *= 1 + (avg["handoff"] - 55) / 260
    weights["catch_and_shoot"] *= 1 + (avg["catch_and_shoot"] - 55) / 230
    weights["drive"] *= 1 + (avg["drive"] - 55) / 240
    weights["isolation"] *= 1 + (avg["isolation"] - 55) / 260

    # Défense adverse : une consigne est une contrainte que l'attaque essaie d'exploiter.
    dt = normalize_tactics(defending_tactics)
    if dt.get("defensivePriority") == "Limiter 3 pts":
        weights["drive"] *= 1.12; weights["post_up"] *= 1.08; weights["catch_and_shoot"] *= 0.88
    elif dt.get("defensivePriority") == "Protéger peinture":
        weights["catch_and_shoot"] *= 1.12; weights["handoff"] *= 1.06; weights["post_up"] *= 0.92
    if dt.get("helpDefense") == "Forte":
        weights["catch_and_shoot"] *= 1.08; weights["isolation"] *= 0.92
    if dt.get("pressure") == "Forte":
        weights["transition"] *= 1.08; weights["handoff"] *= 1.05

    # Défense de transition / rebond : freine (ou favorise) les contre-attaques adverses.
    weights["transition"] *= max(0.4, min(1.4, 1.0 - 0.28 * transition_stop_value(TacticalModel(dt))))

    # Adaptation : les paniers récents modifient l'action choisie, pas seulement la réussite du tir.
    for a, factor in adaptive_action_weights(team).items(): weights[a] *= factor

    # Fin de match : une équipe menée prend davantage de risques, une équipe devant protège le résultat.
    margin = score_for - score_against
    if clock_remaining <= 300:
        if margin <= -8:
            weights["transition"] *= 1.15; weights["drive"] *= 1.12; weights["catch_and_shoot"] *= 1.10; weights["post_up"] *= 0.92
        elif margin >= 8:
            weights["pick_and_roll"] *= 1.08; weights["post_up"] *= 1.05; weights["transition"] *= 0.90

    return random.choices(list(weights), weights=[max(0.08, v) for v in weights.values()], k=1)[0]


def choose_action_players(team, action, tactics):
    players = team.on_court
    if action == "pick_and_roll":
        scores = [tendency(p, "pick_and_roll_ballhandler") * 0.75 + stat_with_fatigue(p, "playmaking") * 0.25
                  + primary_option_bonus(p, tactics) for p in players]
        ball = weighted_pick(players, scores, 5.0)
        others = [p for p in players if p != ball]
        screen_scores = [tendency(p, "pick_and_roll_screener") * 0.55 + stat_with_fatigue(p, "inside_scoring") * 0.25
                         + stat_with_fatigue(p, "rebounding") * 0.20 for p in others]
        return ball, weighted_pick(others, screen_scores, 8.0)
    key = {
        "transition": "transition", "post_up": "post_up", "handoff": "catch_and_shoot",
        "catch_and_shoot": "catch_and_shoot", "drive": "drive", "isolation": "isolation"
    }.get(action, "usage")
    scores = [tendency(p, key) * 0.72 + stat_with_fatigue(p, "outside_scoring") * 0.10
              + stat_with_fatigue(p, "inside_scoring") * 0.10 + primary_option_bonus(p, tactics) for p in players]
    return weighted_pick(players, scores, 6.0), None


def choose_shot(player, action, tactics):
    if action in ("drive", "post_up"):
        return 2, "paint" if action == "drive" or random.random() < 0.78 else "midrange"
    if action == "catch_and_shoot": return 3, "perimeter"
    if action == "transition":
        if random.random() < 0.64:
            return 2, "paint"
        return 3, "perimeter"
    three = (10 + tendency(player, "three") * 0.62) * 1.10
    two = 20 + tendency(player, "paint") * 0.38 + tendency(player, "midrange") * 0.24
    if tactics.get("offenseStyle") == "Adresse extérieure": three *= 1.15
    if tactics.get("threePointFocus") == "Accentué": three *= 1.20
    if tactics.get("threePointFocus") == "Limité": three *= 0.67
    shot = 3 if random.random() < three / (three + two) else 2
    if shot == 3: return 3, "perimeter"
    return 2, ("paint" if random.random() < 0.63 else "midrange")


def pass_probability(passer, action, tactics):
    model = TacticalModel(tactics)
    base = 0.16 + tendency(passer, "pass") / 420
    if action in ("catch_and_shoot", "handoff", "pick_and_roll"): base += 0.12
    base += model.pass_bonus
    if passer.fatigue > 60: base -= 0.08
    return max(0.04, min(0.68, base))


# =========================================================
# TIR / FAUTES / REBONDS
# =========================================================


def shooting_chance(attacker, defender, shot_type, shot_area, tactics, assisted, adaptation, help_defender=None):
    p = stat_with_fatigue(attacker, "outside_scoring")
    i = stat_with_fatigue(attacker, "inside_scoring")
    ath = stat_with_fatigue(attacker, "athleticism")
    play = stat_with_fatigue(attacker, "playmaking")
    defense = defender_quality(defender, shot_area, tactics, attacker)
    if shot_type == 3:
        chance = 20.0 + p * 0.270 + play * 0.018
        chance -= defense * 0.075
        if attacker.role in ("Shooter", "3&D"): chance += 2.0
        if assisted: chance += 1.2
        chance -= adaptation
        minimum, maximum = 24, 52
    elif shot_area == "midrange":
        chance = 33.0 + p * 0.310 + ath * 0.035 + play * 0.010 - defense * 0.075
        if assisted: chance += 1.0
        chance -= adaptation * 0.65
        minimum, maximum = 30, 58
    else:
        chance = 37.5 + i * 0.300 + ath * 0.035 + play * 0.010 - defense * 0.085
        if attacker.role in ("Scoreur intérieur", "Intérieur"): chance += 2.3
        if primary_position(attacker) in ("PF", "C"): chance += 1.2
        if assisted: chance += 1.0
        chance -= adaptation * 0.45
        minimum, maximum = 38, 66

    if help_defender is not None:
        if shot_area == "paint": chance -= interior_defense(help_defender) * 0.022
        elif shot_area == "midrange": chance -= interior_defense(help_defender) * 0.009
        else: chance -= perimeter_defense(help_defender) * 0.009
    if tactics.get("offenseStyle") == "Adresse extérieure" and shot_area == "perimeter": chance += 1.4
    if tactics.get("offenseStyle") == "Jeu intérieur" and shot_area == "paint": chance += 1.8
    chance -= attacker.fatigue * 0.06
    return max(minimum, min(maximum, chance))


def free_throw_chance(player):
    rating = max(55, min(99, player.outside_scoring * 0.70 + player.inside_scoring * 0.20 + player.playmaking * 0.10))
    return max(56, min(93, 49.5 + rating * 0.40 - player.fatigue * 0.06))


def shoot_free_throws(player, attempts):
    made = 0
    for _ in range(attempts):
        player.free_throws_attempted += 1
        ok = random.random() * 100 <= free_throw_chance(player)
        player._last_ft_made = ok
        if ok:
            player.free_throws_made += 1; player.points += 1; made += 1
    return made


FOUL_SCALE = 2.0       # calibré pour ~19 fautes / équipe / match


def free_throw_rebound(attacking_team, defending_team, shooter):
    """Dernier lancer franc raté = ballon vivant. Retourne True si l'attaque récupère (rebond offensif)."""
    if getattr(shooter, "_last_ft_made", True):
        return False
    if random.random() < 0.15:
        choose_rebounder(attacking_team).rebounds += 1
        return True
    choose_rebounder(defending_team).rebounds += 1
    return False


def foul_probability(attacker, defender, shot_area, defense_tactics, action):
    model = TacticalModel(defense_tactics)
    chance = 0.045
    if shot_area == "paint": chance += 0.055
    elif shot_area == "midrange": chance += 0.015
    else: chance += 0.008
    chance += max(0, attacker.inside_scoring - 75) * 0.0011
    chance += max(0, attacker.athleticism - 80) * 0.0007
    chance += max(0, tendency(attacker, "foul_draw") - 60) * 0.00055
    if action in ("drive", "post_up"): chance += 0.035
    chance += max(0, model.defense["foul_risk"]) * 0.020
    chance += defender.fatigue * 0.0007
    chance *= FOUL_SCALE
    # Joueur en "foul trouble" : il joue plus prudemment.
    if defender.fouls >= 5: chance *= 0.55
    elif defender.fouls >= 4: chance *= 0.75
    return max(0.03, min(0.34, chance))


def offensive_foul_probability(attacker, tactics, action):
    chance = 0.010 + (0.006 if primary_position(attacker) in ("PF", "C") else 0)
    if action in ("drive", "post_up", "isolation"): chance += 0.008
    if tactics.get("tempo") == "Rapide": chance += 0.002
    chance += attacker.fatigue * 0.0002
    return min(0.035, chance)


def offensive_rebound_chance(attacking_team, defending_team, tactics):
    offensive = sum(stat_with_fatigue(p, "rebounding") for p in attacking_team.on_court) / 5
    defensive = sum(stat_with_fatigue(p, "rebounding") for p in defending_team.on_court) / 5
    base = 27 + (offensive - defensive) * 0.20
    if tactics.get("offensiveRebound") == "Agressif": base += 8
    elif tactics.get("offensiveRebound") == "Prudent": base -= 8
    dt = TacticalModel(tactics)
    return max(12, min(42, base + dt.defense.get("offensive_rebound", 0) * 5))


def choose_rebounder(team):
    weights = []
    for p in team.on_court:
        w = stat_with_fatigue(p, "rebounding") * 0.82 + stat_with_fatigue(p, "athleticism") * 0.12 + tendency(p, "box_out") * 0.06
        if primary_position(p) in ("PF", "C"): w += 7
        weights.append(max(1, w))
    return random.choices(team.on_court, weights=weights, k=1)[0]


# =========================================================
# POSSESSION : pipeline complet
# =========================================================


def action_probability_of_pass(attacker, action, tactics):
    return pass_probability(attacker, action, tactics)


TURNOVER_BASE = 10.5     # calibré pour ~13-14 balles perdues / équipe / match

ASSIST_RATE = {
    "catch_and_shoot": 0.72, "handoff": 0.68, "kickout": 0.95, "pick_and_roll": 0.48,
    "transition": 0.52, "drive": 0.36, "post_up": 0.24, "isolation": 0.06,
}
ASSIST_SCALE = 1.5


def credit_assist(team, shooter, action, assisted, passer):
    """Attribue l'assist d'un panier. Si une passe a déjà eu lieu on la crédite ;
    sinon un assist est tiré selon le type d'action (le tir garde ses probabilités)."""
    if assisted:
        if passer is not None and passer is not shooter:
            passer.assists += 1
        return
    if random.random() >= ASSIST_RATE.get(action, 0.30) * ASSIST_SCALE:
        return
    others = [p for p in team.on_court if p is not shooter]
    if not others:
        return
    weights = [max(0.05, (stat_with_fatigue(p, "playmaking") / 100.0) ** 3) * (0.6 + tendency(p, "pass") / 100.0)
               for p in others]
    random.choices(others, weights=weights, k=1)[0].assists += 1


def simulate_possession(attacking_team, defending_team, tactics, defending_tactics, team_fouls=0,
                         score_for=0, score_against=0, clock_remaining=0):
    """Pipeline possession : intention -> exécution -> réaction défensive -> résultat.

    Toutes les décisions utilisateur passent par TacticalModel ou les profils individuels.
    Aucune prise à deux n'est utilisée.
    """
    tactics = normalize_tactics(tactics); defending_tactics = normalize_tactics(defending_tactics)
    action = choose_offensive_action(attacking_team, tactics, score_for, score_against, clock_remaining, defending_tactics)
    attacker, screener = choose_action_players(attacking_team, action, tactics)

    # Passe préalable : le créateur peut transférer le tir à un meilleur receveur.
    assisted = False; passer = attacker
    if action not in ("isolation", "drive", "post_up") and random.random() < action_probability_of_pass(attacker, action, tactics):
        receivers = [p for p in attacking_team.on_court if p != attacker]
        if receivers:
            receiver = weighted_pick(receivers, [tendency(p, "catch_and_shoot") * 0.55 + tendency(p, "drive") * 0.25 + stat_with_fatigue(p, "outside_scoring") * 0.20 for p in receivers], 8.0)
            passer = attacker; attacker = receiver; assisted = True

    shot_type, shot_area = choose_shot(attacker, action, tactics)
    defender = get_matchup_defender(defending_team, attacker, shot_area, defending_tactics)
    secondary_defender = None
    if action == "pick_and_roll" and screener is not None:
        defender, secondary_defender = pick_and_roll_defenders(defending_team, attacker, screener, defender, defending_tactics)
    else:
        secondary_defender = get_help_defender(defending_team, defender, attacker, shot_area, defending_tactics)

    # Une aide crée une vraie conséquence : si elle ferme la zone, l'attaque peut kicker vers un shooter.
    if secondary_defender is not None and action in ("drive", "post_up", "pick_and_roll") and shot_area == "paint":
        model = TacticalModel(defending_tactics)
        kickout_chance = 0.06 + max(0.0, model.defense["kickout"]) * 0.20 + stat_with_fatigue(attacker, "playmaking") / 520
        if tactics.get("ballMovement") == "Très collectif": kickout_chance += 0.08
        if random.random() < min(0.40, kickout_chance):
            shooters = [p for p in attacking_team.on_court if p not in (attacker, screener) and (primary_position(p) in ("PG", "SG", "SF"))]
            if shooters:
                passer = attacker
                attacker = weighted_pick(shooters, [tendency(p, "catch_and_shoot") + stat_with_fatigue(p, "outside_scoring") * 0.20 for p in shooters], 8.0)
                assisted = True; action = "kickout"; shot_type = 3; shot_area = "perimeter"
                defender = get_matchup_defender(defending_team, attacker, shot_area, defending_tactics)
                secondary_defender = None

    # Turnover avant le tir : pression + fatigue + complexité de l'action.
    tm = TacticalModel(tactics); dm = TacticalModel(defending_tactics)
    turnover = TURNOVER_BASE + (100 - stat_with_fatigue(passer, "playmaking")) * 0.035
    turnover += dm.defense["turnover"] * 4
    turnover += max(0.0, dm.defense["pressure"]) * 2.0
    turnover += attacker.fatigue * 0.055
    turnover += 0.8 if action in ("pick_and_roll", "drive") else 0
    turnover += tm.shot_risk * 1.4
    if tactics.get("ballMovement") == "Très collectif": turnover -= 0.7
    if random.random() * 100 < max(5, min(24, turnover)):
        passer.turnovers += 1
        return 0, team_fouls, "turnover"

    # Faute offensive / defensive.
    if random.random() < offensive_foul_probability(attacker, tactics, action):
        attacker.fouls += 1; attacker.turnovers += 1
        return 0, team_fouls, "offensive_foul"

    foul_chance = foul_probability(attacker, defender, shot_area, defending_tactics, action)
    if secondary_defender is not None and shot_area == "paint": foul_chance += 0.008
    if random.random() < foul_chance:
        defender.fouls += 1; team_fouls += 1
        shooting_foul = random.random() < (0.70 if shot_area == "paint" else 0.48 if shot_area == "midrange" else 0.30)
        if shooting_foul:
            # Faute sur un tir raté : lancers francs, PAS de tir tenté au box score.
            # Rare "and-one" : le panier est marqué (tir compté) + 1 seul lancer franc.
            if random.random() < 0.35 and shot_area != "perimeter":
                chance = shooting_chance(attacker, defender, shot_type, shot_area, defending_tactics, assisted, adaptation_strength(attacking_team, action, shot_type, shot_area), secondary_defender)
                if random.random() * 100 <= chance:
                    attacker.shots_attempted += 1; attacker.shots_made += 1; attacker.points += shot_type
                    if shot_type == 3: attacker.three_attempted += 1; attacker.three_made += 1
                    if shot_area == "paint": attacking_team._points_in_paint += shot_type
                    credit_assist(attacking_team, attacker, action, assisted, passer)
                    made = shoot_free_throws(attacker, 1)
                    return shot_type + made, team_fouls, "and_one"
            attempts = 3 if shot_type == 3 else 2
            made = shoot_free_throws(attacker, attempts)
            if free_throw_rebound(attacking_team, defending_team, attacker):
                return made, team_fouls, "foul"      # rebond offensif : l'attaque garde le ballon
            return made, team_fouls, "shooting_foul"
        if team_fouls >= 5:
            made = shoot_free_throws(attacker, 2)
            if free_throw_rebound(attacking_team, defending_team, attacker):
                return made, team_fouls, "foul"
            return made, team_fouls, "bonus_foul"
        return 0, team_fouls, "foul"

    # Tir normal.
    attacker.shots_attempted += 1
    if shot_type == 3: attacker.three_attempted += 1
    adaptation = adaptation_strength(attacking_team, action, shot_type, shot_area)
    chance = shooting_chance(attacker, defender, shot_type, shot_area, defending_tactics, assisted, adaptation, secondary_defender)
    # La tactique offensive crée le contexte du tir : une sélection agressive est plus risquée,
    # une sélection sélective privilégie des situations favorables.
    if tactics.get("shotSelection") == "Sélective": chance += 1.2 if assisted else -0.4
    elif tactics.get("shotSelection") == "Agressive": chance += 0.5
    # Couverture P&R : Drop donne plus de pull-up, Switch peut créer un mismatch, Hedge ralentit le porteur.
    if action == "pick_and_roll":
        coverage = defending_tactics.get("pickAndRollCoverage")
        if coverage == "Drop" and shot_area == "perimeter": chance -= 1.0
        elif coverage == "Switch":
            chance += max(0, (attacker.inside_scoring - defender.defense)) * 0.03
            chance += dm.defense["mismatch_risk"] * 3.0 - dm.defense["switch"] * 1.2
        elif coverage == "Hedge": chance -= 0.7
    # Défense de transition / système "Repli rapide" : gêne les contre-attaques, mais cède un peu en demi-terrain.
    if action == "transition":
        chance -= transition_stop_value(dm) * 1.6
    else:
        chance += max(0.0, -dm.defense["halfcourt"]) * 4.0
    if action == "drive": chance += dm.defense["drive"] * 4.0
    chance = max(5, min(70, chance))
    record_attempt(attacking_team, action, shot_type, shot_area)
    if random.random() * 100 <= chance:
        attacker.points += shot_type; attacker.shots_made += 1
        if shot_type == 3: attacker.three_made += 1
        if shot_area == "paint": attacking_team._points_in_paint += shot_type
        credit_assist(attacking_team, attacker, action, assisted, passer)
        record_success(attacking_team, action, shot_type, shot_area, attacker, assisted)
        return shot_type, team_fouls, "made"

    # Rebond.
    off_reb = choose_rebounder(attacking_team); def_reb = choose_rebounder(defending_team)
    chance_reb = offensive_rebound_chance(attacking_team, defending_team, tactics)
    chance_reb -= TacticalModel(defending_tactics).defense.get("def_rebound", 0) * 6.0
    if random.random() * 100 < chance_reb:
        off_reb.rebounds += 1
        # Deuxième chance : nouvelle action simple, pas de récursion infinie.
        second_action = "post_up" if primary_position(off_reb) in ("PF", "C") else "drive"
        second_type, second_area = choose_shot(off_reb, second_action, tactics)
        second_def = get_matchup_defender(defending_team, off_reb, second_area, defending_tactics)
        off_reb.shots_attempted += 1
        if second_type == 3: off_reb.three_attempted += 1
        second_chance = shooting_chance(off_reb, second_def, second_type, second_area, defending_tactics, False,
                                         adaptation_strength(attacking_team, second_action, second_type, second_area)) + 2
        record_attempt(attacking_team, "second_chance", second_type, second_area)
        if random.random() * 100 <= max(5, min(68, second_chance)):
            off_reb.points += second_type; off_reb.shots_made += 1
            if second_type == 3: off_reb.three_made += 1
            if second_area == "paint": attacking_team._points_in_paint += second_type
            record_success(attacking_team, "second_chance", second_type, second_area, off_reb, False)
            return second_type, team_fouls, "offensive_rebound_score"
        return 0, team_fouls, "offensive_rebound"
    def_reb.rebounds += 1
    return 0, team_fouls, "defensive_rebound"


# =========================================================
# HORLOGE / GAME LOOP
# =========================================================


def possession_duration(tactics, quarter_seconds_remaining):
    tempo = normalize_tactics(tactics).get("tempo")
    if tempo == "Rapide": base = random.uniform(12.3, 15.0)
    elif tempo == "Lent": base = random.uniform(15.0, 18.2)
    else: base = random.uniform(13.4, 15.8)
    t = normalize_tactics(tactics).get("transitionOffense")
    if t == "Agressive": base -= 0.7
    if t == "Repli": base += 0.5
    if quarter_seconds_remaining <= 24: base *= 0.85
    elif quarter_seconds_remaining <= 90: base *= 0.93
    return max(4.0, base)


def quarter_clock_label(seconds_remaining):
    return max(0, int(seconds_remaining))


def apply_minute_end(team):
    # La lineup qui vient de jouer la minute reçoit exactement 1 minute réelle.
    active = set(p.name for p in team.on_court)
    for p in team.roster:
        if p.name in active:
            p.minutes_played += 1; update_fatigue(p)
        else:
            recover_fatigue(p)


def reset_quarter_fouls():
    return 0, 0


# =========================================================
# VALIDATION BOX SCORE
# =========================================================


def audit_team_stats(team):
    players = team.roster
    points = sum(p.points for p in players)
    field_made = sum(p.shots_made for p in players)
    field_att = sum(p.shots_attempted for p in players)
    three_made = sum(p.three_made for p in players)
    three_att = sum(p.three_attempted for p in players)
    ft_made = sum(p.free_throws_made for p in players)
    ft_att = sum(p.free_throws_attempted for p in players)
    if not (0 <= field_made <= field_att and 0 <= three_made <= three_att <= field_att and 0 <= ft_made <= ft_att):
        raise AssertionError(f"Box score incohérent pour {team.name}.")
    reconstructed = 2 * (field_made - three_made) + 3 * three_made + ft_made
    if reconstructed != points:
        raise AssertionError(f"Points incohérents pour {team.name}: {reconstructed} != {points}")
    return {
        "points": points,
        "rebounds": sum(p.rebounds for p in players),
        "assists": sum(p.assists for p in players),
        "turnovers": sum(p.turnovers for p in players),
        "fouls": sum(p.fouls for p in players),
        "free_throws_made": ft_made,
        "free_throws_attempted": ft_att,
        "shots_made": field_made,
        "shots_attempted": field_att,
        "fg_pct": round(field_made / field_att * 100, 1) if field_att else 0.0,
        "three_made": three_made,
        "three_attempted": three_att,
        "three_pct": round(three_made / three_att * 100, 1) if three_att else 0.0,
        "ft_pct": round(ft_made / ft_att * 100, 1) if ft_att else 0.0,
        "possessions": team._possessions,
        "pace": round(team._possessions, 1),
        "points_in_paint": team._points_in_paint,
    }


def team_result(team, score):
    stats = audit_team_stats(team)
    # Le moteur est piloté par les points joueurs : le score de référence doit être identique.
    if stats["points"] != score:
        raise AssertionError(f"Score d'équipe incohérent pour {team.name}.")
    return {
        "name": team.name, "score": score,
        "quarter_scores": team._quarter_scores,
        "stats": stats,
        "players": [
            {
                "name": p.name, "position": p.position, "role": p.role, "overall": p.overall,
                "outside_scoring": p.outside_scoring, "inside_scoring": p.inside_scoring,
                "athleticism": p.athleticism, "playmaking": p.playmaking, "defense": p.defense,
                "perimeter_defense": round(perimeter_defense(p)), "interior_defense": round(interior_defense(p)),
                "rebounding": p.rebounding, "stamina": p.stamina, "points": p.points,
                "shots_made": p.shots_made, "shots_attempted": p.shots_attempted,
                "three_made": p.three_made, "three_attempted": p.three_attempted,
                "assists": p.assists, "rebounds": p.rebounds, "turnovers": p.turnovers,
                "fouls": p.fouls, "free_throws_made": p.free_throws_made,
                "free_throws_attempted": p.free_throws_attempted, "minutes": p.minutes_played,
            }
            for p in team.roster
        ],
    }


# =========================================================
# SIMULATION DU MATCH
# =========================================================


def set_overtime_lineup(team):
    """Prolongation : les 5 meilleurs joueurs disponibles (OVR pondéré par la fatigue),
    en respectant la couverture PG/SG/SF/PF/C. Les joueurs à 6 fautes sont exclus."""
    pool = [p for p in team.roster if p.fouls < 6]
    if len(pool) < 5:
        pool = list(team.roster)
    pool.sort(key=lambda p: p.overall * (1 - p.fatigue * 0.004), reverse=True)

    def search(start, chosen):
        if len(chosen) == 5:
            return chosen[:] if position_assignment(chosen) is not None else None
        for i in range(start, len(pool)):
            chosen.append(pool[i])
            found = search(i + 1, chosen)
            if found:
                return found
            chosen.pop()
        return None

    lineup = search(0, []) or pool[:5]
    team.on_court = lineup
    team.bench = [p for p in team.roster if p not in lineup]
    assignment = position_assignment(lineup)
    if assignment:
        for pos, player in assignment.items():
            player.current_position = pos
    else:
        for player in lineup:
            player.current_position = player.primary_position


def simulate_game(team1, team2, rotation1, rotation2=None,
                   starter_names1=None, starter_names2=None,
                   role_map1=None, role_map2=None, tactics1=None, tactics2=None):
    tactics1 = normalize_tactics(tactics1); tactics2 = normalize_tactics(tactics2)
    configure_team_for_match(team1, starter_names1, role_map1)
    configure_team_for_match(team2, starter_names2, role_map2)
    if rotation2 is None:
        rotation2 = build_default_rotation_minutes(team2.roster, team2.starters)
    set_rotation_plan(team1, rotation1); set_rotation_plan(team2, rotation2)
    reset_game_stats(team1); reset_game_stats(team2)
    team1._quarter_scores = [0, 0, 0, 0]; team2._quarter_scores = [0, 0, 0, 0]

    teams = (team1, team2)
    tacs = (tactics1, tactics2)
    score = [0, 0]
    rotation_timeline = []
    state = {"next": 0}          # index de l'équipe qui attaque
    state["next"] = 0 if random.random() < 0.5 else 1

    def rebuild_matchups():
        build_defensive_matchups(team1, team2, tactics2)
        build_defensive_matchups(team2, team1, tactics1)

    def play_period(period, length_min, set_lineup, game_seconds_after):
        """Joue une période (quart ou prolongation). Les fautes d'équipe sont remises à zéro."""
        fouls = [0, 0]
        total = length_min * 60.0
        remaining = total
        last_minute = -1
        while remaining > 0.25:
            current_minute = min(length_min - 1, int((total - remaining) // 60))
            if current_minute != last_minute:
                if last_minute >= 0:
                    apply_minute_end(team1); apply_minute_end(team2)
                set_lineup(team1, current_minute); set_lineup(team2, current_minute)
                ot = period - 3 if period >= 4 else 0
                base_minute = period * 12 if period < 4 else 48 + (period - 4) * 5
                rotation_timeline.append({
                    "minute": base_minute + current_minute + 1,
                    "quarter": period + 1,
                    "overtime": ot,
                    "minute_in_quarter": current_minute + 1,
                    "clock_start": f"{length_min - current_minute:02d}:00",
                    "clock_end": f"{length_min - 1 - current_minute:02d}:00",
                    "team1": [{"name": p.name, "position": p.current_position, "role": p.role} for p in team1.on_court],
                    "team2": [{"name": p.name, "position": p.current_position, "role": p.role} for p in team2.on_court],
                })
                rebuild_matchups()
                last_minute = current_minute
            else:
                # Un joueur exclu (6 fautes) en cours de minute est remplacé immédiatement.
                changed = False
                for team in teams:
                    if any(p.fouls >= 6 for p in team.on_court):
                        set_lineup(team, current_minute); changed = True
                if changed:
                    rebuild_matchups()

            att = state["next"]; dfn = 1 - att
            game_remaining = game_seconds_after + remaining
            points, new_team_fouls, result = simulate_possession(
                teams[att], teams[dfn], tacs[att], tacs[dfn], fouls[dfn],
                score[att], score[dfn], game_remaining
            )
            fouls[dfn] = new_team_fouls
            score[att] += points
            teams[att]._quarter_scores[period] += points
            if result == "foul":
                # Faute non sur tir (ou rebond offensif sur LF) : la même équipe garde le ballon.
                remaining -= min(random.uniform(3.0, 7.0), remaining)
                continue
            teams[att]._possessions += 1
            state["next"] = dfn
            remaining -= min(possession_duration(tacs[att], remaining), remaining)

        apply_minute_end(team1); apply_minute_end(team2)

    for q in range(4):
        play_period(q, 12, lambda team, minute, q=q: apply_rotation_for_minute(team, q * 12 + minute),
                    (3 - q) * 720)

    # Prolongations : nouvelle balle au centre, vrais changements de cinq, minutes/fatigue mises à jour.
    overtime = False
    period = 4
    while score[0] == score[1]:
        overtime = True
        team1._quarter_scores.append(0); team2._quarter_scores.append(0)
        state["next"] = 0 if random.random() < 0.5 else 1
        play_period(period, OT_MINUTES, lambda team, minute: set_overtime_lineup(team), 0)
        period += 1

    result1 = team_result(team1, score[0]); result2 = team_result(team2, score[1])
    return {"team1": result1, "team2": result2, "overtime": overtime,
            "periods": period, "rotation_timeline": rotation_timeline}
