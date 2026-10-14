# Stage Scout 4.2 — Audit complet des entreprises, maintenant

Cette mise à jour ajoute une action **Scan all companies now**. Elle est distincte de **Daily stage scout** et ne remplace pas le scanner quotidien.

## Installation — GitHub Desktop

1. Dans GitHub Desktop : sélectionner le dépôt `stage-scout-v3.2-update`, puis **Repository > Show in Explorer**.
2. Extraire **le contenu** du ZIP fourni **à la racine** du dépôt. Accepter uniquement le remplacement de `company_watchlist.py` ; les autres fichiers sont nouveaux. Ne pas remplacer `companies.csv`, `config.json` ou `data/`.
3. Vérifier dans l'onglet **Changes** la présence de :
   - `.github/workflows/bulk-company-audit.yml`
   - `bulk_company_audit.py`
   - `company_watchlist.py`
   - `tests/test_bulk_company_audit.py`
4. **Commit to main**, puis **Push origin**.
5. Ouvrir GitHub.com > **Actions > Scan all companies now > Run workflow**, branche `main`.
6. Attendre la fin des **16 groupes**, puis du job **Consolidate all companies and publish dashboard**. Les tâches sont parallélisées (8 au maximum). Le temps total dépend des sites et des limites réseau ; ce n'est pas instantané.
7. Dans GitHub Desktop : **Fetch origin > Pull origin** pour récupérer les fichiers mis à jour et le dashboard.

## Résultats disponibles

- `data/bulk-audit-summary.json` : 386 entreprises ciblées (si 386 dans le CSV), 379 actives, combien **tentées**, combien **réellement scannées**, combien d'URL validées, erreurs ou absences d'annuaire.
- `data/company-url-audit.csv` : rapport compatible Excel français (**UTF-8 BOM, séparateur `;`**) avec noms, pays, état, URL ATS candidate, URL réellement scannée, nombre brut d'annonces et **lien vers une recherche Web préremplie** pour chaque entreprise.
- `data/coverage.json` et `dashboard/index.html` : onglet Couverture actualisé.
- `companies.csv` : uniquement les **URL ATS vérifiées après une récupération réussie**, et seulement dans les cellules initialement vides **quand une seule URL candidate existait**. Les URL existantes et les lignes désactivées ne sont pas modifiées.
- `data/jobs.csv`, `data/latest.md`, `data/last_run.json` : sont enrichis des annonces retrouvées et filtrées par Stage Scout. Ils ne sont pas remplacés si aucune annonce n'a été récupérée.

Un téléchargement **full-company-audit-report** est également disponible dans la page de l'exécution Actions > Artifacts.

## Signification des résultats

- `scanned` : une plateforme ATS compatible a répondu au scan, **même avec zéro offre ouverte**. Cela ne prouve pas que la totalité des recrutements de l'entreprise est couverte ; certaines entreprises utilisent plusieurs sites ou filiales.
- `not_found` : aucune correspondance **exacte** détectée dans l'annuaire ATS. **Cela ne signifie pas que l'entreprise ne recrute pas**.
- `unsupported_url` : URL trouvée ou renseignée, mais pas de connecteur adapté.
- `timeout` / `error` : la vérification a échoué ou dépassé son délai. Il faut réessayer ou regarder les logs.
- `disabled` : ligne explicitement désactivée dans le CSV ; ignorée volontairement.

**ATTENTION : on tente toutes les entreprises actives en une seule exécution, mais il est techniquement impossible de garantir un scan réussi de toutes les entreprises à partir de leurs seuls noms.** Certaines utilisent des sites maison, des plateformes qui bloquent l'accès automatisé ou des ATS qui ne sont pas indexés. L'outil ne tente pas de contourner les protections, identifiants ou CAPTCHA.

## Détails techniques

- 16 lots indépendants, 8 en parallèle ; 24 secondes maximum par entreprise pour la découverte et le fetch combinés ; échecs isolés par processus.
- Les recherches se font via l'annuaire `ats-scrapers` et les URL déjà vérifiées (`companies.csv` ou `config.json`) ; **aucune clé API ou service payant n'est nécessaire**.
- Le script ne fait **pas** un « Google Search » automatisé sur 386 entreprises : les liens Google présents dans le rapport servent au contrôle manuel ultérieur.
- Les résultats de chaque lot sont sauvegardés en artifacts. Le regroupement refuse de publier un « audit complet » si un lot entier manque.
- La recherche automatique quotidienne conserve son cycle habituel et ne re-scanne pas toutes les entreprises chaque jour.
- Les workflows GitHub Actions peuvent consommer des minutes de calcul suivant les conditions de ton dépôt GitHub.

## Dépannage

Si **Scan all companies now** n'est pas visible dans Actions, vérifier que `.github/workflows/bulk-company-audit.yml` existe **sur la branche `main` de GitHub.com**. Ne pas utiliser « Re-run jobs » d'une vieille exécution : lancer une nouvelle action.

Si le job de regroupement échoue, ouvrir **Consolidate all companies and publish dashboard**, copier les dernières lignes d'erreur, et ne pas lancer de `git push --force`.
