# Mission 3 — bilan de validation

Version vérifiée le 21 octobre 2026, sur `main`, à partir de la mission 2 (`c603515`).

## Résultats

**780 annonces classées, 780 identifiants distincts, aucune erreur d’analyse.**

| Potentiel PDM | Annonces |
| --- | ---: |
| Explicite | 50 |
| Élevé | 303 |
| Moyen | 213 |
| Faible | 202 |
| Incertain | 12 |

| Catégorie de missions | Annonces |
| --- | ---: |
| Mechanical Design | 110 |
| R&D / Product Development | 552 |
| Simulation / CAE | 149 |
| Testing / Validation | 358 |
| Manufacturing / Production | 242 |
| Systems Integration | 324 |
| Robotics / Mechatronics | 42 |
| Automation / Control | 269 |
| Materials / Processes | 135 |
| Energy / Thermal | 109 |
| Quality | 186 |
| Supply Chain / Logistics | 97 |
| Project Management | 120 |
| Other | 56 |

Les catégories sont multiples : leur somme dépasse 780. Le potentiel PDM et le score technique restent indépendants. **773 annonces appellent une vérification humaine**, notamment parce qu’au moins une contrainte pratique manque ; ce nombre ne signifie pas 773 potentiels PDM incertains. Aucune correction manuelle de l’utilisateur n’était présente dans le nouveau cache au premier calcul.

## Évaluation préalable

40 annonces réelles figées et annotées avant le traitement de l’historique : conception, simulation, thermique, essais, robotique, production, industrialisation, supply chain, thèses explicites et descriptions insuffisantes.

- Premier passage : accord PDM sur 32/40 ; toutes les catégories minimales attendues retrouvées sur 28/40.
- Après examen des missions et corrections : accord PDM sur **40/40** ; catégories minimales attendues retrouvées sur **40/40**.
- Ce jeu a servi à ajuster les règles. Ces résultats ne constituent **pas une mesure indépendante de précision**. Le rappel des catégories ne mesure pas les catégories attribuées en trop.
- Les annotations de pertinence faible/modérée/forte restent qualitatives ; les scores sur 100 ne sont pas des probabilités calibrées.
- Le CSV conserve les justifications automatiques, l’appréciation indépendante, les preuves de mission, la confiance et les cas à vérifier. Les contraintes incomplètes justifient une vérification humaine sur les 40 cas.

Fichiers : `tests/fixtures/assessment_review_20261020.json`, `data/job-assessment-evaluation.csv` et `data/job-assessment-evaluation.summary.json`.

## Vérifications

- `python -m unittest discover -s tests -v` : **203 tests passent**, dont **49 tests dédiés au classificateur**. Les wrappers exécutent aussi les **23 cas JavaScript** des interfaces existante et de présélection.
- Cache réel : seconde exécution = **780 résultats réutilisés**, zéro recalcul, fichier strictement inchangé.
- Identifiants : correspondance exacte entre les 780 annonces et les 780 analyses, sans doublon.
- Comparaison binaire avec la sauvegarde préalable : `jobs.csv`, enrichissements, couverture et `config.json` inchangés.
- Tests d’intégration : descriptif enrichi réellement classé, ajout d’une annonce sans recalcul des autres, invalidation sur contenu/profil/règles, conservation des corrections et anciens identifiants, cache malformé et échec isolé.
- Tests UI : filtres cumulés, catégories OU, tris distincts, accès aux faibles, décisions séparées des candidatures, import/export ancien et nouveau, corrections conservées et textes échappés.
- Revue indépendante : défaut de validation d’un cache corrompu corrigé avec test de régression ; aucune autre anomalie matérielle signalée dans les portions revues.
- Chrome réel avec les 780 annonces : cinq tris, filtres catégories OU, accès aux 202 potentiels faibles, liens offre/candidature, décision + candidature coexistantes, notes/favoris/correction après rechargement et export/import, Couverture conservée. Contrôle visuel à 1440×1000 et 390×844, panneau de détail et filtres mobiles ; aucun débordement horizontal ni erreur JavaScript.

## Changements

- `job_classifier.py` : analyse déterministe contextualisée et extraction prudente des contraintes.
- `assessment_cache.py`, `assess_jobs.py`, `build_dashboard.py` : persistance, empreintes, recalcul, évaluation, intégration après enrichissement et entreprises prioritaires.
- `dashboard-src/app.js`, `index.template.html`, `style.css`, `dashboard/index.html` : Présélection, filtres, tris, explications, décisions et corrections.
- `data/job_assessments.json` : résultats persistants par identifiant ; fichiers d’évaluation réels et nouveaux tests.
- Workflows quotidien, scan massif, enrichissement, reconstruction et Pages adaptés ; nouvelle action `Reclassify jobs`.
- `PRESELECTION.md` et `README.md` : utilisation, fonctionnement, limites, commandes et retour arrière.

## Limites

Le moteur est fondé sur des règles lexicales et contextuelles FR/EN, sans modèle de langage ni API payante. Les formulations implicites, les titres trompeurs et les sections inhabituelles peuvent encore produire des erreurs ; certaines catégories restent larges. Les descriptions partielles réduisent la confiance. L’éligibilité, les langues et la disponibilité personnelles inconnues restent à confirmer ; une thèse explicite ne garantit pas son acceptation par l’EPFL.

Le suivi demeure local au navigateur, exportable en JSON, sans synchronisation serveur. Le scanner, ses sources et ses exclusions n’ont pas été modifiés. Aucun CV, lettre de motivation ou automatisme de candidature n’a été développé.

La procédure d’exploitation et de retour arrière est détaillée dans [PRESELECTION.md](PRESELECTION.md).
