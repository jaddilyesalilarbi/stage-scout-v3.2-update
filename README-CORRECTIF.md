# Stage Scout - correctif des tests pour la liste de 386 entreprises

## Cause
Le test `test_real_template_and_fr_ch_targets` supposait que toutes les entreprises
etait en FR ou CH et que toutes etaient activees. Ce n'est plus vrai pour la liste
elargie, volontairement internationale avec quelques lignes desactivees.

Le test `test_rotation_covers_whole_registry` attendait un parcours complet en
14 jours. A 10 cibles par jour, les 379 cibles actives prennent 38 jours.

## Installation
1. Garder le fichier `companies.csv` actuel et toutes les donnees.
2. Dans le depot local, remplacer uniquement `tests/test_coverage.py` par le
   fichier inclus dans cette archive (dans le dossier `tests`).
3. Dans GitHub Desktop: `Commit to main` puis `Push origin`.
4. Sur GitHub: Actions > Daily stage scout > Run workflow (nouvelle execution).

## Verification
Le nouveau test verifie que:
- les cibles FR/CH sont toujours presentes;
- les lignes peuvent etre internationales, desactivees ou sans pays confirme;
- le CSV est structure correctement et sans doublons;
- le nombre de jours teste s'ajuste automatiquement au nombre de cibles actives.

Resultats de validation locale: 72/72 tests passent avec le CSV initial (43
entreprises), et 72/72 avec le nouveau CSV (386 entrees, 379 actives).

Ce correctif ne modifie ni les scrapers, ni le dashboard, ni la configuration,
ni le suivi de candidatures.
