# Le profil JSON

Un profil décrit **le matériel et l'intention d'impression**, jamais l'image. Le même profil doit pouvoir tourner sur n'importe quelle photo et donner un résultat cohérent. C'est ce qui rend les profils réutilisables et versionnables.

## Exemple complet

```json
{
  "name": "Duotone rose fluo / noir",
  "description": "Portrait contrasté, 2 passages, papier crème 170g",

  "inks": [
    {
      "name": "fluo-pink",
      "label": "Fluorescent Pink",
      "color": "#FF48B0",
      "order": 1,
      "opacity": 0.85,
      "screen_angle": 15,
      "max_coverage": 0.9
    },
    {
      "name": "black",
      "label": "Black",
      "color": "#000000",
      "order": 2,
      "opacity": 1.0,
      "screen_angle": 45,
      "max_coverage": 0.85
    }
  ],

  "paper": {
    "color": "#F4EFE2",
    "label": "Crème 170g non couché"
  },

  "separation": {
    "method": "density-lsq",
    "total_ink_limit": 1.7,
    "black_generation": 0.6,
    "preserve_highlights": true
  },

  "tone": {
    "gamma": 1.1,
    "contrast": 0.15,
    "black_point": 0.02,
    "white_point": 0.98,
    "desaturate": 0.0
  },

  "halftone": {
    "method": "clustered-dot",
    "lpi": 60,
    "dot_shape": "round"
  },

  "output": {
    "dpi": 300,
    "format": "png",
    "bit_depth": 8,
    "invert": false,
    "long_edge_mm": 297,
    "registration_marks": true,
    "margin_mm": 5
  }
}
```

---

## Racine

| Champ | Type | Défaut | Rôle |
|---|---|---|---|
| `name` | string | requis | Nom lisible du profil, repris dans le `todo.md`. |
| `description` | string | `""` | Note libre : papier, machine, intention. |

---

## `inks[]`

Un objet par encre, donc par passage machine. Au moins un, pas de maximum théorique — mais au-delà de 4, le repérage devient difficile en pratique.

| Champ | Type | Défaut | Rôle |
|---|---|---|---|
| `name` | string | requis | Identifiant technique, utilisé dans les noms de fichiers. Minuscules, tirets. Unique. |
| `label` | string | `name` | Nom lisible, repris dans le `todo.md`. |
| `color` | hex sRVB | requis | Couleur de l'encre en aplat 100 % sur **papier blanc**. |
| `order` | entier ≥ 1 | position dans la liste | Ordre de passage machine. Unique, contigu à partir de 1. |
| `opacity` | 0.0–1.0 | `0.85` | Opacité de l'encre. Pilote la simulation de surimpression. |
| `screen_angle` | degrés | voir [halftone.md](halftone.md) | Angle de trame. |
| `max_coverage` | 0.0–1.0 | `1.0` | Plafond d'encrage pour ce calque seul. |

### `color` — le champ qui compte

C'est la donnée la plus déterminante du profil, et celle qui mérite le plus d'attention. Les valeurs des chartes constructeur sont des approximations écran ; les encres fluo en particulier sont hors gamut sRVB et ne peuvent pas être représentées fidèlement.

En pratique : imprimer un aplat 100 % de chaque encre sur le papier réel, scanner ou photographier la planche en lumière neutre, et prélever la couleur. Un profil calé sur un nuancier maison donne des séparations nettement plus justes qu'un profil théorique.

### `opacity`

Les encres riso sont à base de soja et semi-transparentes : c'est ce qui permet à deux passages de se mélanger optiquement pour créer une troisième couleur. `1.0` modéliserait une encre parfaitement opaque, ce qui n'existe pas en riso. `0.8` à `0.9` correspond au comportement usuel. Le noir est le plus couvrant.

### `order`

L'ordre de passage a un effet physique réel. La convention par défaut est **du plus clair au plus foncé** : l'encre claire imprimée en premier macule moins le tambour du passage suivant, et le noir posé en dernier garde son contraste. Certains ateliers font l'inverse pour des raisons de séchage — d'où le paramètre.

---

## `paper`

| Champ | Type | Défaut | Rôle |
|---|---|---|---|
| `color` | hex sRVB | `#FFFFFF` | Couleur du support. |
| `label` | string | `""` | Description, reprise dans le `todo.md`. |

La simulation part de la couleur du papier, pas du blanc pur. Sur un crème, un ivoire ou un kraft, l'aperçu est très différent — et la séparation aussi, puisque le papier constitue la densité de base à laquelle s'ajoutent les encres.

---

## `separation`

| Champ | Type | Défaut | Rôle |
|---|---|---|---|
| `method` | enum | `density-lsq` | `luminance`, `duotone`, `tritone`, `cmyk`, `density-lsq`. Voir [separation.md](separation.md). |
| `total_ink_limit` | float ≥ 0 | `2.4` | Somme maximale des couvertures, tous calques confondus. `1.7` = 170 %. |
| `black_generation` | 0.0–1.0 | `0.5` | Quantité de gris remplacée par l'encre la plus foncée. Utilisé par `cmyk` et `density-lsq`. |
| `preserve_highlights` | bool | `true` | Force la couverture à zéro sous un seuil bas, pour garder des blancs francs. |
| `curves` | objet | `null` | Courbes de réponse explicites par encre. Requis pour `duotone` / `tritone`, ignoré ailleurs. |

### `total_ink_limit`

Au-delà d'un certain encrage cumulé, le papier sature : l'encre ne sèche plus, macule au passage suivant et gondole la feuille. La limite dépend du papier — un 170 g non couché encaisse plus qu'un 80 g. `1.7` à `2.0` est prudent, `2.4` est un maximum raisonnable.

Quand la limite est franchie, le solveur ne coupe pas brutalement : il redistribue vers l'encre la plus foncée, qui apporte le plus de densité par unité de couverture. Voir [separation.md](separation.md).

### `black_generation`

Un gris neutre peut s'obtenir en superposant toutes les encres colorées, ou en utilisant directement l'encre foncée. Monter `black_generation` privilégie la seconde option : moins d'encre totale, meilleur séchage, repérage moins critique dans les ombres — mais des ombres plus plates. Descendre donne des noirs plus riches et colorés, au prix d'un encrage plus lourd.

### `curves`

Pour `duotone` et `tritone`, chaque encre reçoit une courbe de réponse sur la luminance, exprimée en points de contrôle `[luminance, couverture]` interpolés :

```json
"curves": {
  "fluo-pink": [[0.0, 0.0], [0.35, 0.85], [0.75, 0.45], [1.0, 0.0]],
  "black":     [[0.0, 1.0], [0.45, 0.55], [0.8, 0.05],  [1.0, 0.0]]
}
```

La luminance va de `0.0` (ombres) à `1.0` (hautes lumières), la couverture de `0.0` à `1.0`. La zone où deux courbes se recouvrent produit le mélange des deux encres — c'est là que se joue le rendu.

---

## `tone`

Corrections appliquées **avant** la séparation, sur l'image en espace linéaire.

| Champ | Type | Défaut | Rôle |
|---|---|---|---|
| `gamma` | float > 0 | `1.0` | `> 1` éclaircit les tons moyens, `< 1` les assombrit. |
| `contrast` | −1.0–1.0 | `0.0` | Contraste en S autour du gris moyen. |
| `black_point` | 0.0–1.0 | `0.0` | Niveau ramené au noir. Recadre l'histogramme par le bas. |
| `white_point` | 0.0–1.0 | `1.0` | Niveau ramené au blanc. |
| `desaturate` | 0.0–1.0 | `0.0` | `1.0` sépare une version entièrement désaturée de la photo. |

La risographe écrase les basses lumières et délave les hautes lumières. Un léger relèvement du contraste (`0.1` à `0.2`) et un point noir non nul compensent presque toujours. C'est le premier réglage à ajuster quand un tirage sort mou — avant de toucher à la séparation.

`--preview-only` existe précisément pour itérer vite sur ces cinq valeurs.

---

## `halftone`

| Champ | Type | Défaut | Rôle |
|---|---|---|---|
| `method` | enum | `clustered-dot` | `none`, `clustered-dot`, `error-diffusion`, `bayer`. |
| `lpi` | entier | `60` | Linéature, en lignes par pouce. Plage utile 40–85. |
| `dot_shape` | enum | `round` | `round`, `ellipse`, `square`, `line`. Uniquement pour `clustered-dot`. |
| `matrix_size` | entier | `8` | Taille de la matrice de Bayer. Uniquement pour `bayer`. |

Détails, contraintes et table des angles dans [halftone.md](halftone.md).

---

## `output`

| Champ | Type | Défaut | Rôle |
|---|---|---|---|
| `dpi` | entier | `300` | Résolution de sortie. `600` recommandé avec `clustered-dot`. |
| `format` | enum | `png` | `png` ou `tiff`. |
| `bit_depth` | `8` ou `16` | `8` | 16 bits n'a d'intérêt qu'en ton continu. |
| `invert` | bool | `false` | `false` = **noir signifie 100 % d'encre**. |
| `long_edge_mm` | float | `297` | Longueur du grand côté en millimètres. Le petit côté suit le ratio de la source. |
| `registration_marks` | bool | `true` | Ajoute des repères de calage dans la marge. |
| `margin_mm` | float | `5` | Marge blanche ajoutée sur les quatre côtés, qui accueille les repères. |

Conventions détaillées et description des fichiers produits dans [sorties.md](sorties.md).

---

## Validation

Le profil est validé intégralement **avant** tout calcul, pour éviter d'échouer après plusieurs minutes de traitement.

### Erreurs bloquantes (code de sortie `2`)

- Champ requis manquant : `inks`, `name` ou `color` d'une encre.
- Couleur hexadécimale mal formée.
- `name` d'encre dupliqué.
- `order` dupliqué ou non contigu à partir de 1.
- Valeur hors bornes : `opacity`, `max_coverage`, `black_point`, `white_point`, `desaturate` hors `[0, 1]`, `gamma` ≤ 0, `lpi` ≤ 0.
- `black_point` ≥ `white_point`.
- `method` inconnue.
- `duotone` / `tritone` sans `curves`, ou `curves` référençant une encre absente.
- Nombre d'encres incompatible avec la méthode : `luminance` en exige 1, `duotone` 2, `tritone` 3, `cmyk` 3 ou 4.

### Avertissements (n'interrompent pas)

- Deux encres à moins de 15° d'écart de trame, en `clustered-dot` → risque de moiré. L'écart tient compte de la périodicité des trames à 90° : 5° et 95° sont le même angle. Les autres méthodes de tramage n'utilisent pas les angles, l'avertissement ne s'y applique pas.
- `total_ink_limit` > 2.4 → risque de saturation du papier.
- `dpi / lpi` < 8 en `clustered-dot` → dégradés en escalier, voir [halftone.md](halftone.md).
- `bit_depth: 16` avec un tramage actif → sans effet, la sortie est binaire.
- Une encre dont `color` est très proche de `paper.color` → contribution quasi nulle.
- Clé inconnue dans une section → probable faute de frappe, la valeur est ignorée.

Chaque avertissement remonte sur la sortie standard **et** dans le `todo.md`, pour qu'il atteigne la personne qui imprime et pas seulement celle qui lance le programme.
