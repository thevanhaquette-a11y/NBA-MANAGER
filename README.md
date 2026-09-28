# NBA Manager V38

Simulateur de match NBA (données 2KRatings NBA 2K27) : tu choisis ton équipe, ton cinq majeur,
les minutes de chaque joueur (240 au total) et tes tactiques, puis tu lances le match.

## Lancer le jeu

```
python server.py
```
Puis ouvrir http://localhost:8000/NBA_MANAGER_INTERFACE/  (`/api/version` doit répondre `V38`).

Aucune dépendance : Python 3.10+ suffit.

## Base de joueurs

`data/players_2k27.json` contient les joueurs. **Aujourd'hui seules PHI et SAS sont jouables.**
Pour importer les 30 équipes, sur un PC avec Internet :

```
INITIALISER_BASE.bat        (ou : python setup_database.py)
```
L'import n'écrase la base actuelle que s'il est complet et validé (sauvegarde dans `data/backups/`).
`python validate_database.py` liste les joueurs dont il manque des notes : ils sont ignorés par le jeu
(14 aujourd'hui) et signalés dans les menus.

## Tester le moteur

```
python test_engine.py 60
```
Simule 60 matchs, vérifie la cohérence (box score, 240 minutes, 6 fautes max, score par période) et
compare les moyennes aux ordres de grandeur NBA.

## Nouveautés V38

**Bugs corrigés**
- Une faute sur tir ne compte plus comme tir tenté (FGA gonflés d'environ 5/match).
- And-one : 1 seul lancer franc (avant : 3).
- Fin de match : la logique « équipe menée / équipe devant » se déclenchait dans les 5 premières
  minutes au lieu des 5 dernières (l'horloge passée était le temps écoulé).
- Prolongations : vrais changements de cinq, minutes et fatigue mises à jour, joueurs à 6 fautes
  exclus, score par période incluant les OT.
- Un joueur qui atteint 6 fautes est remplacé immédiatement, plus à la minute suivante.
- Une faute non sur tir laisse maintenant le ballon à l'attaque (avant : possession perdue).
- Dernier lancer franc raté : rebond (défensif ou offensif).

**Réalisme** (valeurs par équipe et par match, 60 matchs PHI-SAS)
- Passes décisives ~10 -> ~23, balles perdues ~9 -> ~14, fautes ~11 -> ~19, lancers francs ~11 -> ~23.
- Le tireur n'est plus toujours le meilleur profil : tirage pondéré par les tendances.
- Joueur en « foul trouble » (4-5 fautes) : défense plus prudente.

**Tactiques** : « Repli rapide » (système et transition), « Sécuriser » vs « Agressif » (rebond
défensif), « Meilleur scoreur », Switch/mismatch, pression, contest et « Protéger peinture » ont
maintenant un effet réel.

**Adversaire IA** : minutes selon le niveau (34 -> 14 min) et tactiques adaptées au profil des titulaires.

**Interface** : équipes indisponibles grisées, joueurs ignorés signalés, tableau des scores par
période (OT compris), possessions et points dans la peinture, échappement HTML des noms.

**Technique** : serveur multi-thread, démarrage protégé par `if __name__ == "__main__"`,
effectifs codés en dur et fichiers obsolètes supprimés, un seul README.

## Limites connues
- Postes rigides : un cinq sans PG/SG/SF/PF/C éligible est refusé (pas de malus de poste).
- Une seule équipe pilotée par l'utilisateur ; l'IA ne change pas de tactique pendant le match.
- Pas de sauvegarde de saison, de blessures ni de repos.
