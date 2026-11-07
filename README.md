# Stage Scout 4.3

La classification PDM et la vue Présélection sont documentées dans [PRESELECTION.md](PRESELECTION.md) : filtres, décisions, cache, recalcul et limites de l’analyse.

## Historique : Stage Scout 3.0 — Recherche TRÈS large de stages et PDM

Cette version remplace Stage Scout 2.0. Elle conserve **les données déjà publiées dans ton dépôt** (`data/jobs.csv`), mais ajoute une vraie recherche sur les sites carrières, une recherche mondiale et l'exclusion des offres en allemand.

## Qu'est-ce qui change ?

| | Ancienne version | Version 3.0 |
| --- | --- | --- |
| Jeu de données ATS | 2 requêtes ciblées / jour | **4 sources ATS complètes / jour**, rotation de 12 sources sur 3 jours |
| Sites carrières visités | 2 URL saisies manuellement | 2 URL + **découverte automatique d'environ 12 entreprises prioritaires / jour** (si nom exact dans l'annuaire) |
| Indeed (JobSpy) | 2 recherches / jour | **8 recherches / jour**, rotation sur 59 couples métier / ville / pays |
| Pays | Majoritairement France / Suisse | France, Suisse, Europe, Canada, États-Unis, Singapour, Australie |
| Langue allemande | Pénalité légère | **Rejet** si annonce en allemand ou allemand obligatoire |
| Reporting | Compteurs généraux | Ajout `excluded_by_language`, `source_counts` et colonne `language` dans le CSV |

**Important :** chaque source ATS se présente comme un *snapshot* public d'offres. Ce n'est pas une garantie d'ouverture aujourd'hui. Clique toujours sur le site officiel de l'employeur pour valider l'annonce. Notre agent ne cherche que des **annonces publiées**, pas les offres cachées ni les candidatures spontanées.

## Installer sur ton dépôt GitHub existant (Windows + GitHub Desktop)

Pas besoin de créer un nouveau dépôt, ni de forker ATS Scrapers/JobSpy.

1. Dans **GitHub Desktop**, sélectionne ton dépôt actuel `stage-scout-v2`.
2. Clique **Fetch origin**, puis **Pull origin** si proposé, pour sauvegarder localement les derniers résultats produits par GitHub Actions.
3. Clique `Repository > Show in Explorer`.
4. Décompresse le fichier **stage-scout-v3.zip** ; ouvre le dossier `stage-scout-v3` et copie **son contenu** dans le dossier du dépôt. Accepte les remplacements des fichiers du programme. Ne touche pas à `.git` ni aux données existantes dans `data/jobs.csv`.
5. GitHub Desktop > *Changes* > message `Expand search and filter German listings` > **Commit to main** > **Push origin**.
6. Sur github.com, ouvre ton dépôt > **Actions** > **Daily stage scout** > **Run workflow**.
7. Une fois le workflow terminé, ouvre `data/last_run.json`, `data/latest.md` et `data/jobs.csv` dans **Code**.

Un premier test avec cette version peut prendre **plusieurs minutes**. Si le job échoue, copie le texte de l'étape en rouge ; le budget des sources peut être réduit dans `config.json`.

## Réglages pratiques dans `config.json`

### Langues

```json
"excluded_languages": ["de"],
"exclude_required_german": true
```

La langue de l'annonce est détectée via le champ `language` de l'ATS quand il existe, puis heuristiquement à partir du titre et du descriptif. Un descriptif trop court ou ambigu est conservé plutôt que rejeté à tort. Cela ne peut pas être parfait à 100 % ; vérifier les offres ambiguës.

Une offre **en anglais à Zurich, Bâle, Berlin, Munich** reste admise tant que l'allemand ne constitue pas une exigence obligatoire.

### Couverture des sites carrières

- `company_careers` : URLs de carrières **confirmées** ; elles sont interrogées à chaque passage.
- `priority_companies` : entreprises que l'agent favorise dans le score.
- `company_discovery.enabled: true` : tente aussi de retrouver l'URL ATS des entreprises par correspondance **exacte de nom** dans l'annuaire public du projet ATS Scrapers. Limité à `companies_per_day: 8`, en rotation quotidienne, pour éviter de solliciter les sites à l'excès.
- Pour ajouter beaucoup d'entreprises depuis un CSV : `python add_companies.py entreprises.csv`. La première colonne peut être `entreprise`, `company`, `name`, etc.

**Attention :** l'annuaire ne sait pas tout identifier (filiales, noms juridiques, pages privées). Une entreprise sans correspondance exacte peut encore être ajoutée manuellement dans `company_careers` avec son URL ATS publique. Le programme évite d'associer automatiquement une entreprise à un homonyme approximatif.

### Balayage des grandes plateformes ATS

```json
"ats_dataset": {
  "enabled": true,
  "scan_mode": "source_sweep",
  "providers_per_day": 4,
  "max_candidates_per_provider": 2000,
  "providers": ["greenhouse", "workday", "lever", "ashby", "smartrecruiters", "successfactors", "oracle", "icims", "workable", "personio", "softgarden", "eures"]
}
```

Chaque jour, jusqu'à quatre **sources complètes** sont tentées individuellement (slices CSV), puis filtrées localement par nature du contrat et métiers. Cela évite la recherche répétée d'un unique mot-clé, et le téléchargement multi-GB du catalogue complet. Les 12 sources sont parcourues en trois jours, sous réserve de disponibilité et des limites du serveur source.

Le lanceur impose désormais un délai par source et continue les autres recherches lorsqu'une plateforme est trop lente. Tu peux réduire `providers_per_day` à `2` si les timeouts restent nombreux. Pour intensifier : `6`, mais surveille la mémoire, les temps et les conditions d'accès.

### Recherche ouverte Indeed

`jobspy.searches_per_day: 6` ; rotation parmi 59 recherches géographiques et sectorielles couvrant le génie mécanique, les structures, l'intégration et la R&D. Les requêtes ne sont **pas** filtrées à un seul pays ; le score ne donne qu'un bonus géographique.

Le moteur utilisé est `indeed`. Des sources comme Glassdoor et LinkedIn posent plus de problèmes de stabilité ou de règles d'automatisation et ne sont pas activées par défaut. Respecte les limites et conditions des plateformes ; pas de contournement de CAPTCHA ni d'utilisation d'identifiants personnels.

### Pertinence

`minimum_score: 32` (un peu plus large qu'avant). Tu peux descendre à `25` si tu veux davantage de résultats, au prix de plus d'annonces éloignées de ton profil. Les exclusions de langue restent appliquées séparément.

## Lire les résultats

- **`data/latest.md`** : toutes les offres pertinentes observées aujourd'hui (150 maximum, ensuite consulter CSV).
- **`data/jobs.csv`** : historique cumulé, avec l'URL, la source, le score et maintenant `language`.
- **`data/last_run.json`** : `observed`, `matches`, `new`, `excluded_by_language`, `source_counts`, `errors`.
- **Issues GitHub** : alerte si une offre inédite est trouvée.

Le nombre `observed` correspond aux annonces que les sources ont renvoyées au programme et qui ont été retenues lors de la présélection pour les grands catalogues, **pas** à l'intégralité des millions d'offres du dataset ATS.

Le filtrage des anciennes lignes allemandes s'applique aussi à `data/jobs.csv` dans la limite des champs disponibles dans l'ancien CSV. Les lignes avec une description trop courte ou langue inconnue sont conservées pour éviter les faux négatifs.

## Tests

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scout.py --sample --output data-sample
```

Aucune API payante n'est nécessaire dans la configuration livrée. GitHub Actions possède un quota de minutes sur les dépôts privés ; surveille `Settings > Billing and licensing` si tu augmentes beaucoup la fréquence ou le nombre de sources.


## Correctif v3.1 : recherches protégées contre les blocages

Dans la v3, un téléchargement ATS volumineux ou une recherche Indeed lente pouvait bloquer
l'ensemble de `python scout.py`, sans indication du site en cours car la sortie était tamponnée.
Le journal GitHub affichait alors seulement `Run python scout.py`.

La v3.1 utilise **`python -u run_safe.py`** :

- Chaque site, recherche Indeed ou tranche ATS tourne dans un processus distinct, avec **timeout**.
- Après un timeout ou une erreur, les **autres sources continuent** ; les résultats des sources terminées restent disponibles.
- Les logs affichent `[SCAN]` avant chaque source, `[RESULT]` après, et `[SKIP]` en cas de budget épuisé.
- La durée du programme est plafonnée par `scan_limits.max_runtime_seconds` (16 min par défaut), avec une limite GitHub Actions de 22 min pour l'étape.
- `data/last_run.json` comporte `source_health` : nombre de sources terminées, lentes, en échec ou non explorées faute de temps, ainsi que le nom de chacune.

Les timeouts **ne prouvent pas que la source est hors service** : seulement qu'elle n'a pas répondu dans le temps imparti. Un workflow explicitement annulé dans GitHub reste annulé ; cette version ne peut pas empêcher une annulation manuelle ou imposée par la plateforme.

Pour contrôler les sources prévues sans accès réseau :

```powershell
python run_safe.py --show-plan
```

Pour une exécution locale :

```powershell
python -u run_safe.py
```

Pour une mise à jour depuis la v3, copie le contenu de l'archive dans ton dépôt GitHub en **préservant `.git` et le dossier `data/`**. Fais ensuite Commit/Push depuis GitHub Desktop et relance le workflow. Ne supprime pas l'historique CSV : les nouveaux résultats s'y ajouteront.

## Fiabilité / limites

- Les **30 tests hors réseau** valident le classement, le suivi, le filtre allemand et les connecteurs simulés.
- Le premier lancement sur GitHub est nécessaire pour confirmer que les 12 sources choisies répondent correctement à la collecte réelle.
- Certains sites carrières ont un accès limité, une publication différée ou une API différente : ils ne sont pas garantis couverts par l'annuaire.
- Les stages et PDM nécessitent une vérification d'éligibilité EPFL, de nationalité/visa, de durée et de dates.
- Aucune candidature n'est envoyée automatiquement.

**Dépendances open source :** [ATS Scrapers](https://github.com/kalil0321/ats-scrapers), [JobSpy](https://github.com/speedyapply/JobSpy), [langdetect](https://pypi.org/project/langdetect/).
