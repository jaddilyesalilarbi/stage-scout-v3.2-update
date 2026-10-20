# Stage Scout 4.3 — étape 1 : liens et descriptions

Périmètre : collecte et conservation du contenu des annonces, deux liens dans le
dashboard, préparation de la migration. Aucun changement de classification PDM,
de score, de filtres de présélection ou des workflows GitHub Actions.

## Architecture

- `run_safe.py` orchestre les sources dans des processus avec délais et budgets.
- `company_watchlist.py` et `bulk_company_audit.py` passent aussi par les
  normalisations de `scout.py`. Les collectes sont consolidées par ce même moteur.
- `scout.py` normalise, dédoublonne, applique les règles existantes, puis fusionne
  les annonces dans `data/jobs.csv` et produit les rapports.
- `job_content.py` partage la validation des liens, le nettoyage du texte et la
  fusion du contenu entre collecteur, migration et générateur du dashboard.
- `build_dashboard.py` injecte les données dans le dashboard autonome, à partir
  de `dashboard-src/`. `dashboard/index.html` est l'artefact généré.
- Le suivi navigateur reste dans `stage-scout-review-v4`, indexé par les mêmes
  identifiants. Le format d'import/export du suivi est inchangé.

## Champs et collecte

| Champ CSV | Usage |
| --- | --- |
| `url` | Compatibilité avec les rapports et exports existants ; lien d'offre prioritaire pour les nouvelles annonces, sinon lien disponible |
| `description_url` | Page de lecture de l'offre, lorsqu'identifiée |
| `apply_url` | Lien de candidature explicitement fourni par la source |
| `description` | Tout le texte reçu, nettoyé du HTML, avec paragraphes et listes ; aucune coupe à 300 caractères |
| `description_source` | Source du texte, qui peut différer de la source privilégiée lors d'un dédoublonnage |
| `description_status` | `source_provided`, `partial`, `missing` ou `legacy_excerpt` |
| `description_excerpt` | Extrait de compatibilité de 300 caractères |

ATS : `url` et `apply_url` sont traités séparément. Ashby et Lever conservent leurs
liens de lecture et de candidature ; Lever assemble ouverture, corps, sections
avec leurs titres et conclusion. Les descriptions Greenhouse et Arbeitnow sont
conservées. Les collectes ATS directes utilisent l'enrichissement fourni par
`ats-scrapers` (activé par défaut dans la version épinglée).

JobSpy : `job_url` devient le lien de lecture et `job_url_direct` le lien de
candidature. La collecte demande explicitement `fetch_description=True`.
SerpApi conserve ses liens de candidature sans les qualifier de pages de lecture.
Adzuna est marqué `partial`, son texte pouvant être un extrait.

Les suffixes de candidature Lever `/apply`, Ashby `/application` et Recruitee
`/c/new` sont réversibles uniquement sur leurs hôtes et chemins reconnus.
Les autres liens inconnus ne sont pas transformés.

Le dédoublonnage conserve la priorité des sources existante pour les métadonnées
et récupère le texte le plus long ainsi que les liens manquants des copies. Une
observation plus courte ou vide ne remplace pas un texte déjà archivé plus long.
La provenance du texte retenu est conservée. Cette règle privilégie la conservation
du contenu ; elle ne garantit pas que le texte le plus long soit le plus récent.

Les identifiants sont inchangés, y compris la base de calcul historique du lien
pour les annonces sans nom d'entreprise. Les colonnes CSV supplémentaires sont
conservées, ainsi que `status` et `first_seen`. L'écriture passe par un fichier
temporaire puis remplacement, pour ne pas tronquer l'historique en cas d'échec.

## Dashboard

Deux boutons distincts : « Voir l'offre » et « Postuler ». Un bouton reste
désactivé lorsque son lien n'est pas identifié. Une annonce historique dont l'URL
est encore ambiguë conserve un bouton « Lien historique ».

Le texte complet apparaît lorsqu'il existe, avec sa provenance ; sinon l'extrait
historique reste visible. Les textes sont échappés avant affichage. La recherche
porte aussi sur le corps complet et l'export de sélection inclut les deux liens.
Favoris, notes, statuts et import/export du suivi gardent leur fonctionnement.

## Migration préparée, à appliquer séparément après validation

`migrate_job_content.py` ne fait **aucune requête réseau**. Il ne lance pas les
filtres ni le classement : aucune annonce n'est éliminée. Il conserve ordre,
identifiants, dates, suivi et colonnes supplémentaires. Les ID absents ou dupliqués
et les CSV malformés font refuser l'opération.

Par défaut, il simule sur 25 lignes et ne crée aucun fichier :

```powershell
rtk proxy .venv\Scripts\python.exe migrate_job_content.py --limit 25
```

Pour préparer un enrichissement, fournir un JSON normalisé déjà collecté via les
extracteurs de cette version, sous la forme `{"jobs": [...]}`. Chaque objet fournit
`company`, `title`, `location`, `source`, `description`, `description_url`,
`apply_url`, et éventuellement son `id`. Par exemple, le résultat de
`scout.fetch_ats_direct(...)` pour une entreprise choisie peut être exporté dans
ce format lors d'une collecte ultérieure explicitement décidée. Ce script ne
recollecte pas lui-même les anciennes annonces.

Le rapprochement utilise l'ID explicite ou la même identité entreprise/titre/lieu
que le collecteur. Des candidats contradictoires sont signalés dans `ambiguous`
et ne sont pas utilisés. Aucune nouvelle annonce n'est insérée par la migration.

```powershell
# Simulation d'un lot, à examiner avant application
rtk proxy .venv\Scripts\python.exe migrate_job_content.py --raw-input collected.json --offset 0 --limit 25

# Application future du même lot, uniquement après validation de cette étape
rtk proxy .venv\Scripts\python.exe migrate_job_content.py --raw-input collected.json --offset 0 --limit 25 --apply
```

Sans `--raw-input`, seuls le schéma et les liens inversables avec certitude sont
préparés. Un ancien extrait n'est jamais présenté comme une description complète.
Les URL historiques ambiguës restent dans `url`. Les exécutions répétées sur les
mêmes données sont sans effet. `--offset` permet de choisir le lot suivant.

Une application qui change des lignes crée une copie exacte
`jobs.csv.pre-v43-<date UTC>.bak` avant remplacement. Pour restaurer, recopier cette
sauvegarde vers `jobs.csv` et reconstruire le dashboard. Un échec d'écriture peut
laisser un fichier `.tmp` à côté de la sauvegarde ; l'original reste intact.
Ne pas appliquer la migration pendant une collecte qui écrit le même CSV.

## Vérifications et limites

```powershell
rtk proxy .venv\Scripts\python.exe -m unittest discover -s tests -v
rtk proxy node --test tests/dashboard_content.test.cjs
rtk proxy .venv\Scripts\python.exe build_dashboard.py
```

Les tests JavaScript exécutent le vrai `app.js` avec une interface DOM minimale :
liens, échappement du texte, recherche, suivi local et export CSV. Ils sont aussi
inclus dans la suite Python si Node.js est disponible.

Une source peut fournir un texte incomplet, une offre expirée ou aucun lien de
candidature séparé. `source_provided` signifie « texte fourni par la source »,
sans garantir sa complétude. Certains scrapers ATS plafonnent déjà le contenu en
amont à 25 000 caractères ; Stage Scout conserve tout ce qu'ils transmettent.
Les délais et budgets existants restent applicables aux récupérations détaillées.
Il n'y a pas de récupération générique par navigateur des pages dynamiques ou
protégées. Aucun scan massif ni application de migration n'est requis pour
installer cette étape. Les tests de régression utilisent des réponses simulées,
sans campagne de validation réseau de toutes les sources.
