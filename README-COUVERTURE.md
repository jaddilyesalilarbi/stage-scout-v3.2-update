# Stage Scout 4.1 — Couverture des entreprises et CSV

Mise à jour **de ton dépôt Stage Scout 4.0 existant**, compatible avec ses filtres Europe / langue / saison de la version 3.3. **Ne crée pas de nouveau dépôt.**

## Ce qu'elle ajoute

- Onglet **Couverture** dans `dashboard/index.html`, avec recherche par entreprise, filtres France/Suisse/autres, état du dernier contrôle, dernier essai, dernière réussite, URL et nombre d'annonces brutes récupérées.
- Historique persistant `data/coverage.json` : les entreprises non sélectionnées le jour J gardent la date de leur dernière tentative. L'ancien `data/last_run.json` est utilisé pour initialiser l'historique lors de la première construction du dashboard, mais **uniquement pour les scans directement identifiables**.
- Fichier **`companies.csv`** à modifier librement (fourni avec 43 cibles FR/CH). Les entreprises déjà définies dans `config.json` sont également visibles. Le bouton **Exporter toutes les entreprises (.csv)** permet de récupérer une liste complète incluant celles de `config.json`.
- Scan en rotation de **10 entreprises CSV par jour** par défaut. Pour chacune : URL carrières fournie -> interrogation directe si compatible ATS ; sinon, nom exact -> recherche d'une page ATS connue (Greenhouse, Lever, Ashby, Workday, etc.). Le moteur général ATS et JobSpy reste actif.
- Distinction stricte entre **scan ATS réussi**, **recherche dans l'annuaire**, **URL non compatible**, **erreur** et **aucun contrôle effectué**. Une URL renseignée n'est pas une garantie de scan.

## Installation (GitHub Desktop)

1. Ouvre ton dépôt existant via **Repository > Show in Explorer**.
2. Décompresse `stage-scout-v4.1-coverage-update.zip` et copie **le contenu** du dossier extrait directement à la racine du dépôt, en remplaçant les fichiers présents.
3. **Ne supprime pas** `.git`, `config.json`, `data/jobs.csv`, `data/last_run.json`, `data/new.md` ou tes autres fichiers. Le ZIP ne contient aucun de ces fichiers.
4. Sur GitHub Desktop : **Commit to main** puis **Push origin**.
5. Sur github.com : **Actions > Build dashboard only > Run workflow**. Cette action ajoute l'onglet sans rechercher de stages. Puis, sur le PC, **Fetch origin > Pull origin**, et ouvre `dashboard/index.html`.
6. Pour commencer les vérifications des URL : **Actions > Daily stage scout > Run workflow**. Après la fin, fais Fetch/Pull et recharge l'interface. `data/coverage.json` apparaîtra également sur GitHub.

## Remplir les entreprises dans Excel ou un éditeur CSV

Modifie le fichier **`companies.csv`** à la racine du dépôt (ou récupère une version complète depuis l'onglet Couverture), avec ces colonnes exactes :

| name | country | careers_url | enabled | notes |
|---|---|---|---|---|
| ABB | CH | https://adresse-officielle-du-site-ATS | yes | |
| Safran | FR | | yes | Vérifier l'URL |

- `name` : nom exact de l'entreprise (obligatoire ; aucun doublon).
- `country` : pays **ciblé** pour ton suivi (`FR`, `CH`, éventuellement `DE`, `BE`, etc.). Ce n'est pas nécessairement le pays du siège social ni le pays de chaque offre.
- `careers_url` : URL **réelle de la plateforme de recrutement** de l'entreprise (idéalement sa racine ATS). Ne colle pas un lien vers une offre précise ni un lien de résultats Google. Laisse vide si tu ne connais pas le lien : l'agent essaiera une découverte automatique par nom exact.
- `enabled` : `yes` pour rechercher, `no` pour exclure l'entreprise des scans programmés (elle restera listée comme désactivée).
- `notes` : facultatif, **pas de données sensibles** si tu publies l'interface.

Le fichier utilise UTF-8 et des virgules, mais le lecteur accepte aussi le CSV avec points-virgules que produit parfois Excel français. Lors d'un enregistrement depuis Excel, choisis de préférence **CSV UTF-8**. Après modification : Commit/Push et lance **Daily stage scout**. **Build dashboard only** affiche les changements de CSV mais ne visite aucun site.

## Ce que signifient les statuts

| État | Signification |
|---|---|
| Site scanné | Le connecteur ATS a reçu une réponse exploitable, même si elle contenait 0 offre. |
| Scannée via annuaire / Annuaire seulement | Des offres renvoyées après récupération d’un ATS identifié confirment le scan. Une simple recherche de nom sans résultat ne le confirme pas. |
| Non trouvée | L'annuaire n'a pas retrouvé de correspondance exacte. |
| URL non compatible | La page indiquée n'est pas prise en charge par un connecteur ATS automatique. |
| Erreur / Délai dépassé | Le contrôle a échoué ou a été interrompu, les autres sources continuent. |
| Pas encore scannée | Entreprise inscrite mais pas encore sélectionnée dans la rotation. |

**Important :** les grandes collectes `ATS dataset / ...` et les résultats Indeed donnent des offres de nombreuses entreprises, mais ne prouvent **pas** que chaque page carrière a été parcourue. Elles restent séparées dans la mesure de couverture.

Pour accélérer la rotation, tu peux ajouter (facultatif) à ton `config.json` :

```json
"watchlist": { "companies_per_day": 15 }
```

Cette ligne est à placer dans l'objet JSON principal, avec une virgule appropriée. **N'augmente pas trop ce nombre** : GitHub Actions impose une limite de durée et le scanner dispose d'un budget global. Les URL génériques non reconnues demanderont un connecteur spécifique, qui pourra être développé plus tard.

### Vérifications

```bash
python -m unittest discover -s tests -v
python run_safe.py --show-plan
python build_dashboard.py
```

**Compatibilité / protection des données :** cette mise à jour ne change pas les filtres des stages, ne remplace pas ton historique `jobs.csv` et ne modifie pas les favoris/statuts/notes enregistrés localement dans ton navigateur. Ceux-ci continuent d'être stockés dans `localStorage` ; pense à les exporter régulièrement avec le bouton de sauvegarde.
