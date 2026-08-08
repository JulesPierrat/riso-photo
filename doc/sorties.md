# Fichiers produits

## Contenu de `output/`

```
project/nom_projet/output/
├── 01_fluo-pink.png    # un calque par encre, préfixé par l'ordre de passage
├── 02_black.png
├── preview.png         # simulation du tirage final
├── todo.md             # plan d'impression
└── run.json            # paramètres effectifs du run
```

Le dossier est **vidé et régénéré intégralement** à chaque exécution. Rien de ce qui s'y trouve ne doit être considéré comme durable — voir [cli.md](cli.md) pour le détail du comportement d'écrasement.

---

## Les calques

### Nommage

```
<ordre sur 2 chiffres>_<name de l'encre>.<format>
```

Le préfixe numérique garantit que les fichiers s'affichent dans l'ordre de passage dans n'importe quel explorateur — au moment d'imprimer, l'ordre est la première chose qu'on veut lire sans réfléchir.

### Convention de valeur

Par défaut (`output.invert: false`) : **noir = 100 % d'encre, blanc = pas d'encre.**

C'est ce qu'attendent la plupart des pilotes riso et des imprimeurs : le calque se lit comme un tirage de l'encre en noir. Certains prestataires demandent l'inverse ; `output.invert: true` produit alors des positifs inversés.

En interne, la couverture vaut toujours `1.0` pour l'encre pleine, quelle que soit cette option. L'inversion n'est appliquée qu'à l'écriture, ce qui évite les erreurs de signe dans tout le pipeline.

### Format et profondeur

| Réglage | Effet |
|---|---|
| `format: png` | Sans perte, universel. Le défaut. |
| `format: tiff` | Pour les flux de prépresse qui l'exigent. |
| `bit_depth: 8` | 256 niveaux. Suffisant partout. |
| `bit_depth: 16` | N'a d'intérêt qu'en ton continu (`halftone.method: "none"`) sur des dégradés très longs. Sans effet si un tramage est actif, la sortie étant binaire — le programme le signale. |

Les calques sont écrits en **niveaux de gris**, jamais en RVB : un calque n'a pas de couleur, la couleur est l'encre chargée dans la machine. C'est le `todo.md` qui fait le lien entre fichier et encre.

### Géométrie

Les dimensions en pixels découlent de `output.long_edge_mm` et `output.dpi`. Le petit côté suit le ratio de la source — le programme ne recadre ni ne déforme jamais.

```
côté_long_px = long_edge_mm / 25.4 × dpi
```

`output.margin_mm` ajoute une marge blanche sur les quatre côtés, **en plus** du format utile. Elle accueille les repères de calage et donne la prise papier nécessaire au massicot.

Si la source ne permet pas d'atteindre la résolution demandée, un avertissement de sous-résolution est levé : le programme agrandit, mais le dit. Un calque interpolé vers le haut puis tramé produit une bouillie de points que l'aperçu ne montre pas toujours.

### Repères de calage

Avec `registration_marks: true`, des croix de repérage sont ajoutées dans la marge aux quatre coins, **identiques et à la même position sur tous les calques**.

Elles servent à aligner physiquement les passages : on cale le second passage sur le premier en superposant les croix à contre-jour. Le repérage d'une risographe dérive typiquement de 1 à 2 mm d'une feuille à l'autre — ces repères permettent de mesurer la dérive et de compenser au chargement.

Elles se trouvent dans la marge, donc hors du format final : elles disparaissent au massicot. D'où l'avertissement du `todo.md` de ne pas couper avant vérification.

---

## `preview.png`

Simulation RVB du tirage, obtenue en recomposant les couvertures par le modèle multiplicatif décrit dans [separation.md](separation.md), en partant de `paper.color`.

Par défaut, l'aperçu est calculé à partir des couvertures **continues**, avant tramage : rapide et lisible. `--preview-halftoned` le calcule à partir des calques tramés — plus fidèle au grain réel, nettement plus lent, utile pour vérifier qu'une linéature ne bouche pas les ombres.

**Ce que l'aperçu montre bien :** la répartition tonale, le contraste, quelle encre porte quelle partie de l'image, l'équilibre entre les calques.

**Ce qu'il ne montre pas :** la couleur exacte. Les encres fluo sortent du gamut sRVB et seront toujours sous-estimées à l'écran ; la diffusion optique du papier rend le tirage réel un peu plus dense. Voir les limites du modèle dans [separation.md](separation.md).

---

## `run.json`

Trace exhaustive du run : profil effectivement appliqué après valeurs par défaut, fusion d'un éventuel `config.json` local et surcharges CLI, plus les métadonnées du traitement.

```json
{
  "riso_photo_version": "0.1.0",
  "project": "portrait-anna",
  "config_source": "config/duotone-rose-noir.json",
  "config_overrides": ["project/portrait-anna/config.json", "--dpi 600"],
  "source_image": "source.jpg",
  "source_size_px": [3024, 4032],
  "output_size_px": [4961, 6614],
  "profile": { "...": "profil résolu, intégral" },
  "layers": [
    { "file": "01_fluo-pink.png", "ink": "fluo-pink", "order": 1,
      "coverage_mean": 0.41, "coverage_max": 0.88 }
  ],
  "total_ink_max": 1.52,
  "warnings": []
}
```

Deux usages : reproduire à l'identique un tirage réussi plusieurs mois plus tard, et servir de signature du dossier — sa présence indique que `output/` a bien été produit par le programme et peut être écrasé sans risque.

Les couleurs y repartent en hexadécimal, telles qu'écrites dans le profil : ce sont elles qu'on recopiera pour refaire le tirage.

---

## `todo.md`

Le plan d'impression, destiné à être imprimé ou envoyé au prestataire. Il répond à trois questions : quels fichiers, dans quel ordre, avec quels réglages.

Il est généré à partir des **données réelles** du calcul — couvertures mesurées, dimensions effectives, avertissements accumulés — et non d'un gabarit figé.

### Exemple

```markdown
# portrait-anna — plan d'impression

Profil : Duotone rose fluo / noir
Source : source.jpg (3024 × 4032) → sortie 2480 × 3307 px @ 300 dpi (A4 portrait)
Papier : Crème 170g non couché
Encrage total maximum atteint : 152 % (limite du profil : 170 %) ✅

## Ordre de passage

### Passage 1 — Fluorescent Pink
- Fichier : `01_fluo-pink.png`
- Trame : points agglomérés, 60 lpi, 15°
- Couverture moyenne : 41 % · maximum : 88 %
- Note : encre claire imprimée en premier, limite le maculage au passage suivant.

### Passage 2 — Black
- Fichier : `02_black.png`
- Trame : points agglomérés, 60 lpi, 45°
- Couverture moyenne : 34 % · maximum : 85 %
- Note : porte le contraste. En cas de rendu trop lourd, baisser `black_generation`.

## Points de vigilance
- Laisser sécher **au moins 2 h** entre le passage 1 et le passage 2.
- Repérage : tolérance risographe ≈ 1 à 2 mm. Les repères de calage sont inclus
  dans la marge de 5 mm — ne pas massicoter avant vérification.
- Charger tout le papier en une seule fois, dans le même sens, pour les deux passages.
- Aucune paire d'encres à moins de 15° d'écart de trame : pas de risque de moiré.
```

### Contenu

**En-tête** — profil, source et dimensions effectives, papier, encrage total atteint face à la limite du profil.

**Un bloc par passage**, dans l'ordre machine — encre, fichier, réglages de trame, couvertures moyenne et maximale, et des notes générées à partir du rôle réel de l'encre dans cette séparation :

| Situation | Note |
|---|---|
| L'encre la plus claire ouvre la série | Rappelle pourquoi : moins de maculage au passage suivant. |
| Le premier passage **n'est pas** l'encre la plus claire | Signale l'écart à l'usage et invite à vérifier que l'ordre est voulu. |
| L'encre la plus dense | Indique que c'est elle qui porte le contraste. |
| Couverture moyenne sous 3 % | Suggère de retirer ce passage : un tour de machine pour presque rien. |
| `max_coverage` atteint sur plus de 1 % de l'image | Chiffre la surface aplatie et invite à relever le plafond. |
| Couverture à 100 % sur plus de 1 % | Même constat, mais sans conseil : l'encre donne déjà tout ce qu'elle peut. |

La ligne « Trame » décrit **ce qui est réellement dans les fichiers**, pas ce que le profil réclame : tant que le tramage n'est pas appliqué, elle annonce du ton continu à tramer par le pilote.

**Points de vigilance** — séchage entre passages, tolérance de repérage, consignes de chargement papier, plus tous les avertissements du run : sous-résolution, plafond d'encrage atteint, angles de trame trop proches, `bit_depth` sans effet.

Les avertissements apparaissent ici en plus de la sortie standard, précisément pour qu'ils atteignent la personne qui imprime — qui n'est pas toujours celle qui a lancé le programme.
