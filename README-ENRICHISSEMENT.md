# Enrichissement historique — Stage Scout 4.3, mission 2

L'enrichissement complète l'historique existant. Il ne lance pas la recherche
quotidienne, ne reclasse aucune annonce et ne modifie pas les scores ou le suivi.

## Données conservées

`data/jobs.csv` reste la source du scan quotidien et n'est **jamais réécrit** par
`backfill_jobs.py`. Les identifiants, dates, scores, statuts et colonnes personnelles
restent intacts. Les annonces expirées ou non retrouvées restent présentes.

Les résultats sont dans `data/job-enrichment-state.json`, sous `results[ID]` :

- URL d'origine et liens sources d'origine, pour traçabilité ;
- `detail_url` officiel identifié et `apply_url` fourni par la source ;
- description récupérée, provenance et état `complete`, `partial` ou `missing` ;
- titre, entreprise et localisation constatés, preuves d'identification ;
- disponibilité constatée, confiance, date, erreur et nombre de tentatives.

Le dashboard fusionne ces résultats en mémoire avec le CSV. `description_url`
reste un alias de compatibilité de `detail_url`. La signature porte sur ID,
entreprise, titre, localisation et URL sources : si un scan récent change ces
champs, un ancien résultat n'écrase pas la nouvelle observation. Il est signalé
comme périmé et sera retraité à la prochaine reprise.

Les favoris, notes et statuts du navigateur restent indexés par les mêmes ID,
dans `stage-scout-review-v4`. L'onglet Couverture et les filtres sont conservés.

## Exécuter ou reprendre

```powershell
# Une annonce restante par famille de plateformes, avant un premier gros passage
rtk proxy .venv\Scripts\python.exe backfill_jobs.py --sample --workers 3

# Traiter l'historique ; reprendre avec exactement la même commande
rtk proxy .venv\Scripts\python.exe backfill_jobs.py --workers 4 --max-seconds 900

# Reprendre un lot limité ou des ID précis
rtk proxy .venv\Scripts\python.exe backfill_jobs.py --limit 25
rtk proxy .venv\Scripts\python.exe backfill_jobs.py --ids id1,id2

# Recontrôler aussi les annonces déjà complètes ou expirées
rtk proxy .venv\Scripts\python.exe backfill_jobs.py --retry --limit 25

# Refaire l'audit et le dashboard sans requête réseau
rtk proxy .venv\Scripts\python.exe backfill_jobs.py --report-only
rtk proxy .venv\Scripts\python.exe build_dashboard.py
```

Par défaut, les résultats complets avec identité vérifiée et les annonces
explicitement expirées ne sont pas interrogés de nouveau. Les autres résultats
sont réessayés, y compris les accès refusés : aucun mécanisme ne contourne une
protection de site. `--retry` permet un contrôle explicite des résultats terminés.
Les annonces jamais tentées passent avant les échecs à réessayer, pour qu'un
budget court ne bloque pas indéfiniment les dernières lignes de l'historique.

Le programme utilise au plus quatre tâches par défaut et deux requêtes par hôte,
des délais de connexion/lecture, un cache partagé et un seul retry pour certains
codes temporaires. Un `Retry-After` trop long est signalé plutôt que raccourci.
Le budget limite le lancement de nouvelles annonces ; les requêtes déjà engagées
se terminent avec leurs délais. Un verrou empêche deux écritures simultanées du
même checkpoint. La progression est écrite après chaque résultat, par fichier
temporaire puis remplacement ; les verrouillages transitoires de Windows sont
réessayés. Après interruption, les résultats déjà enregistrés sont réutilisables.

Chaque passage avec des annonces à interroger crée une copie exacte du CSV et du
checkpoint précédent dans `.backfill-backups/<date UTC>/`. Ces sauvegardes locales
sont ignorées par Git. Elles ne sont pas supprimées automatiquement.
Si une nouvelle récupération est plus courte ou échoue, le corps précédemment
vérifié est conservé dans `archived_content`. L'audit se fonde toujours sur le
checkpoint effectivement enregistré, même si une écriture finale échoue.

## Reprise sur GitHub

Dans **Actions → Enrich existing jobs → Run workflow**, conserver les valeurs par
défaut pour reprendre les annonces restantes. Cette action partage le verrou
`daily-stage-scout` avec les scans et ne lance pas le scout quotidien.

Elle sauvegarde le checkpoint et les CSV d'origine comme artefact GitHub pendant
30 jours, y compris après un échec. Avant publication, elle récupère `origin/main`
et fusionne les éventuels nouveaux commits, puis reconstruit le dashboard depuis
le CSV le plus récent. Seuls le sidecar, l'audit, le bilan et le dashboard sont
publiés ; aucun `jobs.csv` ancien n'est renvoyé à la place d'un scan récent.
Un conflit arrête la publication. Aucun reset ni push forcé n'est utilisé.
Le workflow Pages existant reconstruit ensuite l'interface avec le sidecar.

## Audit et interprétation

`data/job-enrichment-audit.csv` contient une ligne par annonce actuelle et tous les
champs de contrôle. `data/job-enrichment-summary.json` distingue :

- `total`, `processed` et `remaining` : total, annonces tentées, annonces jamais
  tentées ou dont la signature source a changé ;
- `complete_descriptions` : corps récupérés et identité vérifiée, indépendamment
  du nombre de caractères de l'ancien texte ;
- `corrected_links` : pages de détail identifiées qui diffèrent du lien d'origine ;
- `expired`, `not_found` et `outcomes` : disponibilité ou issue précise du contrôle ;
- `retryable` : tentatives infructueuses, distinctes des annonces jamais tentées.

`complete` signifie que l'extracteur a récupéré le corps structuré fourni par la
source pour le poste identifié. Il ne garantit pas que l'employeur a renseigné
toutes les informations : durée, date de début, langues ou éligibilité peuvent
manquer. Le texte conservé ne contient aucune information inventée.

Une réponse 404 est classée `not_found`, sans supposer une expiration. Une réponse
410 ou une fermeture explicite est classée `expired`. Les HTTP 401/403/429, erreurs
de réseau et pages sans identité suffisante restent des échecs explicites. Un
formulaire dépourvu de description n'est pas qualifié de page de détail.

Dans l'interface, les dates de contrôle, les expirations et les incertitudes sont
visibles. Une URL non confirmée ne devient pas « Voir l'offre ». Le texte historique
reste consultable si une source ne répond plus.

## Contrôles

```powershell
rtk proxy .venv\Scripts\python.exe -m unittest discover -s tests -v
rtk proxy node --test tests/dashboard_content.test.cjs
```

Les tests couvrent l'identité officielle, les refus de postes différents, les
descriptions longues, la sauvegarde, l'interruption/reprise, l'idempotence, les
échecs d'une source, les signatures périmées et le suivi du dashboard.
