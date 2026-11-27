# Stage Scout 4.3 — Présélection

La vue **Présélection** ajoute le potentiel PDM, les catégories de missions, le score technique et les contraintes aux annonces existantes. **Toutes les offres** et **Couverture** restent disponibles. Aucune candidature n’est envoyée.

## Utilisation

- Le tri initial combine score technique et potentiel PDM. Les tris PDM, technique, date et entreprises prioritaires restent indépendants.
- Plusieurs catégories sélectionnées signifient **OU** ; les autres filtres se combinent avec **ET**.
- Les potentiels faibles sont masqués initialement dans Présélection. « Afficher aussi le potentiel PDM faible » ou le filtre « Faible » permettent de les retrouver. Toutes les offres les conserve.
- « Retenue / À revoir / Écartée / À examiner » est une décision de présélection, indépendante du statut de candidature. Retenue et Postulé peuvent coexister.
- Le détail présente les preuves extraites des missions, les informations manquantes, les contraintes, le texte conservé et les liens séparés vers l’offre et la candidature.
- « Corriger l’analyse » permet une correction locale du potentiel, du score, des catégories et du motif. Une modification ultérieure de la source conserve la correction et affiche une invitation à la vérifier.
- Notes, favoris, statuts, décisions et corrections restent dans `stage-scout-review-v4`, sur le même navigateur et la même origine. L’export/import conserve le format JSON `stage-scout-tracking-v1` et accepte les anciens exports. Exporter avant de changer d’appareil ou de vider le navigateur.

## Analyse et limites

`job_classifier.py` est un moteur déterministe explicable FR/EN. Il distingue les sections de missions, qualifications et présentation de l’entreprise ; il recherche des activités contextualisées, des démarches d’investigation, de conception et de validation, ainsi que des signes de support ou d’exécution. Les qualifications et le secteur de l’employeur ne deviennent pas automatiquement des missions.

Ce moteur utilise des règles lexicales et contextuelles : ce n’est pas une analyse sémantique par modèle de langage. Les descriptions atypiques, les formulations implicites et les autres langues restent moins fiables. Les preuves et corrections manuelles servent à traiter ces cas. Un PDM explicite peut avoir une faible pertinence mécanique ; un stage ordinaire peut avoir un potentiel élevé.

Le score technique est une heuristique bornée sur 100, fondée sur les familles de missions et leur profondeur, séparée du potentiel PDM. Le tri combiné multiplie ce score par un coefficient PDM : explicite 1, élevé 0,8, moyen 0,6, incertain 0,4, faible 0,2. Il ne représente pas une probabilité d’acceptation.

Les contraintes distinguent compatible, incompatible et inconnu. Les paramètres connus sont un Master de mécanique, l’Europe, une durée cible de 5–6 mois et les exclusions linguistiques déjà configurées. Les compétences linguistiques, la date de disponibilité et la nationalité ne sont pas inventées. Un champ absent reste inconnu ; le statut global reste « À vérifier » si une condition manque. Les annonces conservées ne sont pas supprimées par cette analyse. Les exclusions du scanner restent inchangées.

Aucun modèle, service externe, clé ni paiement supplémentaire n’est requis. L’intérêt d’un modèle de langage n’a pas été démontré par cette livraison : aucun connecteur fictif n’est activé. Une future intégration facultative pourra remplacer l’appel pur `classify(job, profile)` avec la même structure de résultat validée, une version/hash distincte, un modèle explicitement choisi et un retour aux règles si le service échoue. Une API nécessiterait sa propre clé et facturation ; un modèle local ses ressources d’exécution. Ce n’est pas inclus dans cette version.

## Données et cache

- `data/jobs.csv` et `data/job-enrichment-state.json` restent les sources, sans migration destructive.
- `data/job_assessments.json` contient les analyses par identifiant, la date, la version des règles et l’empreinte d’entrée.
- L’empreinte couvre le descriptif complet (ou l’extrait disponible), les champs utiles aux contraintes, le profil et le code des règles. Une entrée inchangée est réutilisée sans modifier sa date ni réécrire le cache.
- `manual_override` dans le cache peut aussi contenir une correction partielle versionnée avec Git. Elle est conservée au recalcul. La correction du navigateur a priorité sur les mêmes champs. Les statistiques automatiques ne comptent pas les corrections locales.
- Les anciens identifiants du cache sont conservés. Un échec sur une annonce produit « Incertain » et n’empêche pas les suivantes d’être classées. Un cache JSON corrompu reste intact ; la génération peut continuer avec des analyses temporaires et signale `assessment_meta.cache_error`.

## Commandes et automatisation

Depuis le dépôt, avec l’environnement Python habituel :

```powershell
rtk proxy .venv\Scripts\python.exe assess_jobs.py
rtk proxy .venv\Scripts\python.exe assess_jobs.py --force
rtk proxy .venv\Scripts\python.exe build_dashboard.py
rtk proxy .venv\Scripts\python.exe -m unittest discover -s tests -v
```

La première commande traite les entrées nouvelles ou modifiées. `--force` recalcule toutes les analyses automatiques et préserve les corrections. La reconstruction embarque les analyses dans le HTML autonome.

La classification s’exécute dans `build_dashboard.py`, après la lecture du CSV et la fusion des enrichissements. Les workflows quotidien, scan massif, enrichissement et reconstruction sauvegardent le cache avec le dashboard. **Reclassify jobs**, dans GitHub Actions, fournit le recalcul manuel ; il partage le verrou des scans, fusionne les changements distants et refuse les conflits avant le push. La publication Pages reconstruit depuis les données de `main`.

Une section facultative `assessment_profile` dans `config.json` peut préciser les informations réellement connues, par exemple `duration_months: [5, 6]`, `start_date: "2027-02-01"` ou `languages: ["fr", "en"]`. Ne renseigner que des informations vérifiées. Une modification invalide le cache automatiquement.

## Évaluation

L’échantillon figé `tests/fixtures/assessment_review_20261020.json` contient **40 annonces réelles**, leur texte exact, les catégories attendues et une appréciation indépendante des missions, constituée avant le traitement de l’historique. Les assertions unitaires synthétiques sont séparées de cet échantillon.

```powershell
rtk proxy .venv\Scripts\python.exe assess_jobs.py --evaluate tests/fixtures/assessment_review_20261020.json
```

Cette commande ne classe pas tout l’historique et ne modifie pas son cache. Les résultats détaillés sont dans `data/job-assessment-evaluation.csv` et le résumé adjacent. L’échantillon sert à corriger les règles ; il ne constitue donc pas un jeu de validation indépendant ni une mesure de précision sur toutes les annonces. Les catégories attendues sont un minimum, pas une taxonomie exhaustive. Les cas ambigus restent à vérifier humainement.

## Retour arrière

Le commit `c603515` conserve la version validée après la mission 2. La sauvegarde locale préalable se trouve dans `.backfill-backups/mission3-20261020/` (non publiée). Utiliser un revert Git des commits de mission 3 pour revenir au fonctionnement précédent, sans réinitialisation forcée ni suppression de l’historique. Exporter le suivi du navigateur avant toute opération de maintenance.
