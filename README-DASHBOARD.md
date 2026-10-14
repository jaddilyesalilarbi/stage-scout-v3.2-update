# Stage Scout 4.0 — Tableau de bord interactif

Cette mise à jour **n'altère pas le moteur de recherche**, les filtres 3.3, `config.json` ni le fichier `data/jobs.csv`. Elle ajoute une interface indépendante générée depuis ce CSV.

## Installer dans le dépôt existant

1. Dans GitHub Desktop, ouvrez le dépôt existant via **Repository > Show in Explorer**.
2. Copiez **le contenu** de `stage-scout-v4-dashboard` à la racine de ce dépôt. Conservez les fichiers en place et acceptez de remplacer `.github/workflows/daily-scout.yml`.
3. Faites `Commit to main` puis `Push origin`.
4. Sur github.com, onglet **Actions**, choisissez **Build dashboard only**, puis **Run workflow**. Cette action est rapide et utilise les offres **déjà enregistrées**, sans exécuter à nouveau les scrapers.
5. Dans GitHub Desktop, faites **Fetch origin** et **Pull origin**, puis ouvrez le fichier `dashboard/index.html` dans un navigateur sur votre ordinateur.

La recherche quotidienne `Daily stage scout` générera elle aussi un nouveau `dashboard/index.html` après chaque balayage et l'ajoutera au commit automatisé.

Si la recherche quotidienne est encore en cours, attendez la fin avant de déclencher **Build dashboard only**.

## Utiliser le tableau de bord

- Recherche instantanée (poste, entreprise, ville, descriptif)
- Filtrage par pays, PDM/stage, statut, score, nouveautés de 7 jours, favoris et source officielle
- Tri par score, détection, publication ou entreprise
- Fiches détaillées avec lien vers le site officiel, score, justification, avertissements, notes
- Statuts : À examiner / Intéressant / À postuler / Postulé / Entretien / Refusé / Ignoré
- Export de la sélection en CSV
- Bouton **Sauvegarder le suivi** pour exporter favoris, notes et statuts dans un JSON ; **Restaurer** pour réimporter ce JSON

### IMPORTANT : où sont conservés les statuts ?

Les favoris, statuts et notes modifiés depuis cette interface sont conservés dans **le stockage de ce navigateur** (`localStorage`). Ils ne sont **pas** écrits automatiquement dans `data/jobs.csv` ou GitHub. Cette limitation évite de mettre un jeton GitHub dans une page web, mais signifie que la synchronisation entre plusieurs navigateurs/appareils n'est pas automatique. Sauvegardez régulièrement le suivi en JSON et réimportez-le sur un autre appareil.

Les états déjà inscrits dans `jobs.csv` restent le statut initial des offres. Les ajustements locaux prennent priorité dans le tableau de bord. L'export CSV restitue les statuts visibles et les notes.

### Accès depuis le téléphone (facultatif)

Le résultat `dashboard/index.html` est une page **statique**, sans dépendances externes. Vous pouvez connecter le dépôt à **Cloudflare Pages**, définir le répertoire de sortie sur `dashboard` et laisser le champ de commande de build vide : la page sera alors publiée automatiquement aux mises à jour GitHub. Attention : l'adresse Cloudflare Pages est publique par défaut ; protégez-la avec Cloudflare Access si vous souhaitez en réserver l'accès.

**Ne publiez pas de notes personnelles ou de contacts sensibles sur un site public.** Les notes locales ne font pas partie du fichier HTML généré.

### Vérification locale du générateur

```bash
python build_dashboard.py
python -m unittest discover -s tests -p 'test_dashboard.py' -v
```

Le générateur utilise uniquement la bibliothèque standard Python.
