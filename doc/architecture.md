# Architecture

## Arborescence

```
riso-photo/
├── riso-photo.py              # point d'entrée CLI, volontairement minimal
├── requirements.txt
├── src/
│   ├── cli.py                 # parsing des arguments, orchestration du pipeline
│   ├── config.py              # chargement + validation du profil JSON
│   ├── project.py             # résolution du dossier projet, détection de la source
│   ├── image.py               # chargement, colorimétrie, redimensionnement, courbes tonales
│   ├── inks.py                # définition des encres, passage en espace densité
│   ├── separation.py          # algorithmes de séparation
│   ├── halftone.py            # tramage AM / FM / ordonné, angles
│   ├── output.py              # écriture des fichiers, repères de calage
│   ├── preview.py             # simulation de la surimpression
│   └── report.py              # génération du todo.md et du run.json
├── config/                    # profils d'impression réutilisables
│   ├── mono-noir.json
│   ├── duotone-rose-noir.json
│   ├── trichro-cmj.json
│   └── quadri-riso.json
└── project/
    └── nom_projet/
        ├── source.jpg         # déposé par l'utilisateur — jamais modifié
        └── output/            # entièrement régénéré à chaque run
```

`riso-photo.py` ne contient que la lecture de `sys.argv` et l'appel à `src.cli.main()`. Toute la logique vit dans `src/`, ce qui garde les modules testables sans passer par la CLI.

## Rôle des modules

| Module | Responsabilité | Ne fait pas |
|---|---|---|
| `cli.py` | Enchaîne les étapes, gère les options, affiche la progression et les avertissements. | Aucun calcul image. |
| `config.py` | Lit le JSON, applique les valeurs par défaut, valide, produit un objet `Profile` figé. | N'accède pas au disque projet. |
| `project.py` | Localise `project/<nom>/`, identifie l'image source, prépare et vide `output/`. | Ne lit pas les pixels. |
| `image.py` | Décodage, conversion vers sRGB, passage en linéaire, redimensionnement, courbes `tone`. | Ne connaît pas les encres. |
| `inks.py` | Convertit les couleurs d'encre en densités, construit la matrice de séparation. | Ne sépare pas. |
| `separation.py` | Transforme une image en N cartes de couverture `[0, 1]`. | Ne trame pas, n'écrit rien. |
| `halftone.py` | Transforme une carte de couverture continue en carte binaire tramée. | Ignore la couleur. |
| `output.py` | Encode les PNG/TIFF, ajoute marges et repères de calage. | Ne calcule aucune couverture. |
| `preview.py` | Recompose les couvertures en une simulation RVB du tirage. | N'influence pas les calques. |
| `report.py` | Agrège les statistiques du run et rend `todo.md` + `run.json`. | Ne recalcule rien. |

## Pipeline de traitement

Chaque étape produit une entrée figée pour la suivante.

**1. Résolution** — `project.py` localise le dossier projet et l'image source, `config.py` résout et charge le profil. Échec immédiat si l'un manque.

**2. Validation** — le profil est vérifié intégralement *avant* tout calcul : couleurs bien formées, `order` unique et contigu, angles de trame écartés, limites cohérentes. Les erreurs bloquent, les alertes sont accumulées et remontent dans le `todo.md`.

**3. Chargement** — décodage de la source, conversion vers sRGB (via le profil ICC embarqué s'il existe, sinon sRGB supposé), passage en `float32` linéaire.

**4. Géométrie** — redimensionnement vers la taille cible déduite de `output.long_edge_mm` et `output.dpi`. Si la source est plus petite que la cible, un avertissement de sous-résolution est levé — le programme n'interpole pas silencieusement vers le haut sans le dire.

**5. Corrections tonales** — application de `tone` (point noir, point blanc, gamma, contraste, désaturation) sur l'image linéaire. C'est ici qu'on compense les défauts connus de la risographe, avant que la séparation ne fige quoi que ce soit.

**6. Séparation** — `separation.py` produit N cartes de couverture `float32` dans `[0, 1]`, une par encre. Voir [separation.md](separation.md).

**7. Limitation d'encrage** — application de `max_coverage` par encre, puis de `total_ink_limit` sur la somme. La couverture réelle atteinte est mesurée et conservée pour le rapport.

**8. Aperçu** — `preview.py` recompose les couvertures *avant* tramage par défaut (rapide et lisible). L'option `--preview-halftoned` simule à partir des calques tramés, plus fidèle mais nettement plus lent.

**9. Tramage** — chaque carte de couverture devient une carte binaire selon `halftone`. Sautée si `--no-halftone` ou `halftone.method = "none"`.

**10. Écriture** — encodage des calques, ajout de la marge et des repères de calage, écriture dans `output/`.

**11. Rapport** — `run.json` (paramètres effectifs) et `todo.md` (plan d'impression) sont écrits en dernier, une fois toutes les statistiques connues.

En `--dry-run`, les étapes 1 à 7 s'exécutent normalement et le rapport est affiché sur la sortie standard ; rien n'est écrit sur disque.

## Conventions internes

Ces règles s'appliquent partout dans `src/` et évitent la majorité des bugs de signe et d'échelle.

- **Type et plage** — toutes les images intermédiaires sont des `numpy.float32` dans `[0, 1]`. La conversion en 8 ou 16 bits n'a lieu qu'à l'écriture.
- **Espace linéaire** — dès le chargement, on quitte le sRGB encodé en gamma pour du linéaire. Tout mélange de couleur effectué en gamma est faux ; c'est l'erreur classique de ce type de programme.
- **Axes** — les images couleur sont `(H, W, C)`, les cartes de couverture `(H, W)`, la pile de calques `(N, H, W)` avec `N` dans l'ordre de passage.
- **Sens de la couverture** — en interne, `1.0` signifie **encre pleine**, toujours, quelle que soit la valeur de `output.invert`. L'inversion éventuelle est appliquée au tout dernier moment, dans `output.py`.
- **Immuabilité du profil** — l'objet `Profile` issu de `config.py` n'est jamais modifié en cours de route. Les surcharges CLI (`--dpi`, `--no-halftone`) sont appliquées à la construction, et `run.json` reflète l'état final effectif.

## Gestion des erreurs

| Code de sortie | Cas |
|---|---|
| `0` | Succès, éventuellement avec des avertissements. |
| `1` | Erreur d'usage : projet introuvable, profil introuvable, source ambiguë ou absente. |
| `2` | Profil invalide : la validation a échoué, les messages détaillent chaque champ fautif. |
| `3` | Erreur de traitement : image illisible, mémoire insuffisante, écriture impossible. |

Les avertissements (sous-résolution, encrage plafonné, angles proches) n'interrompent jamais le run mais apparaissent sur la sortie standard **et** dans le `todo.md`.
