# Tramage

## Pourquoi

Une risographe ne sait déposer que de l'encre ou pas d'encre : le master est perforé, chaque trou laisse passer l'encre. Il n'y a pas de demi-teinte physique. Tout dégradé passe donc obligatoirement par une trame — une répartition de points dont la taille ou la densité simule les niveaux intermédiaires.

Deux stratégies :

- **Laisser la risographe tramer** (`method: "none"`). On envoie du ton continu, le pilote applique sa propre trame. Simple, mais on subit ses choix — linéature, angle, courbe de réponse.
- **Tramer soi-même.** On envoie du binaire, la machine le reproduit tel quel. Contrôle total sur le rendu, et c'est ce qui permet d'obtenir le grain caractéristique qu'on recherche généralement en riso.

## Les méthodes

| Méthode | Rendu | Quand l'utiliser |
|---|---|---|
| `none` | Ton continu | Premiers essais, ou prestataire qui préfère gérer sa trame. |
| `clustered-dot` | Trame AM classique, points de taille variable sur grille régulière | Le look riso canonique. Exige des angles distincts par encre. |
| `blue-noise` | Trame FM stochastique | Aucun moiré possible. Rendu granuleux, photographique. Robuste quand le repérage est incertain. |
| `bayer` | Tramage ordonné, motif régulier visible | Rendu rétro assumé, motif graphique. |

### `clustered-dot`

Points centrés sur une grille inclinée, dont le diamètre croît avec la couverture. C'est la trame de l'offset, et celle qui donne à la riso son aspect reconnaissable à basse linéature.

`dot_shape` change le comportement dans les demi-teintes :

- `round` — polyvalent, le défaut.
- `ellipse` — transition plus douce autour de 50 %, évite le raccordement brutal des points ronds qui se touchent tous en même temps.
- `square` — dur, graphique.
- `line` — trame ligne, très marquée.

### `blue-noise`

Seuillage par un masque stochastique dont les positions sont classées de sorte que, pour tout seuil, les points retenus soient répartis le plus uniformément possible — sans jamais former de structure périodique. Le masque est construit une fois par la méthode « vides et amas » d'Ulichney, puis répété sur l'image.

Deux conséquences utiles : **le moiré est structurellement impossible**, et les angles de trame deviennent sans objet. C'est le choix sûr quand on empile 4 encres ou plus, ou quand la machine a un repérage capricieux. En contrepartie, le rendu est bruité et les très basses lumières peuvent s'empâter.

La spécification initiale annonçait de la diffusion d'erreur (Floyd–Steinberg). Elle a été écartée : chaque pixel y dépend du précédent, ce qui interdit toute vectorisation — un calque de 37 Mpx demanderait plusieurs minutes en Python, et il y en a un par encre. Un masque de bruit bleu donne le même caractère FM, se calcule d'un seul coup, et évite au passage les « vers » caractéristiques de Floyd–Steinberg.

### `bayer`

Seuillage par matrice ordonnée de taille `matrix_size` (4, 8 ou 16). Motif régulier parfaitement visible — c'est le but. Rapide, reproductible, esthétique rétro très marquée.

## Égalisation

Une fonction de point brute n'est pas égalisée : demander 25 % de couverture n'encre pas 25 % de la surface. L'écart est faible mais systématique, et décale toute la gamme tonale du tirage.

Le programme tabule donc la fonction de répartition de chaque fonction de point et l'applique aux seuils, ce qui les rend uniformes sur [0, 1]. La surface encrée vaut alors exactement la couverture demandée, pour les quatre formes de point. Mesuré : moins de 0.1 % d'écart aux angles obliques.

**Cas dégénéré.** Quand la trame est alignée sur la grille pixel (0° ou 90°) *et* que la cellule fait un nombre entier de pixels, toutes les cellules retombent sur les mêmes points de la fonction de point. L'égalisation, calculée sur une répartition continue, ne correspond plus à ce petit échantillon discret : à 600 dpi et 60 lpi, la gamme se décalait jusqu'à 4 %. Le programme décale alors la cellule d'un demi pour cent, ce qui décorrèle les phases et ramène l'écart sous 0.2 %. La linéature bouge de 0.3 lpi, invisible.

---

## Linéature (LPI)

La linéature est le nombre de lignes de points par pouce. Elle détermine la finesse de la trame.

| LPI | Rendu |
|---|---|
| 30–45 | Points nettement visibles, très graphique. Effet sérigraphie. |
| 50–70 | Plage courante. Le grain se voit sans dominer. |
| 70–85 | Fin, proche d'une photo. Limite haute de ce que la riso reproduit proprement. |
| > 85 | À éviter. Les points se bouchent, les ombres deviennent des aplats. |

La risographe reproduit mal au-delà de 85 lpi : le master ne tient pas des perforations trop petites et l'encre s'étale. Rester dans la plage utile 40–70 pour la plupart des travaux.

## Relation entre DPI et LPI

Contrainte souvent négligée, avec un effet très visible.

En tramage AM, chaque point occupe une cellule de `dpi / lpi` pixels de côté. Le nombre de niveaux de gris reproductibles vaut donc environ :

```
niveaux ≈ (dpi / lpi)² + 1
```

| DPI | LPI | Cellule | Niveaux |
|---|---|---|---|
| 300 | 60 | 5 × 5 px | ~26 |
| 300 | 40 | 7.5 × 7.5 px | ~57 |
| 600 | 60 | 10 × 10 px | ~101 |
| 600 | 85 | 7 × 7 px | ~50 |

À 26 niveaux, un dégradé de ciel montre des bandes franches. **Sortir à 600 dpi dès qu'on trame en `clustered-dot`** — les risographes travaillent nativement autour de 600 dpi, donc rien n'est perdu.

Le programme avertit quand `dpi / lpi < 8`.

Cette contrainte ne s'applique pas à `blue-noise` ni à `bayer`, qui modulent la densité des points et non leur taille.

---

## Angles de trame et moiré

En tramage AM, deux trames régulières superposées à des angles proches créent une figure d'interférence — le **moiré** : un motif de larges taches qui n'existe dans aucun des deux calques et qui ruine l'image. C'est le principal piège de l'impression multi-passages.

La parade consiste à écarter suffisamment les angles.

| Nombre d'encres | Angles recommandés |
|---|---|
| 2 | 45° / 15° |
| 3 | 15° / 45° / 75° |
| 4 | 15° / 45° / 75° / 0° |

L'écart de 30° entre trames est l'optimum classique de l'offset. Avec 4 encres, on ne peut plus tenir 30° partout : la quatrième reçoit 0°, et on lui attribue **l'encre la plus claire** — c'est sur elle qu'un moiré résiduel se verra le moins. Le jaune est le candidat évident quand il est présent.

45° est l'angle le moins perceptible à l'œil : le réserver à l'encre dominante, généralement le noir.

Le programme **avertit** si deux encres du profil sont à moins de 15° d'écart, en tenant compte de la périodicité à 90° des trames (5° et 95° sont le même angle). Le contrôle a lieu à la validation du profil, avant tout calcul — voir [config.md](config.md).

En cas de doute — beaucoup d'encres, machine à repérage approximatif, aplats de couleur importants — `blue-noise` élimine le problème par construction.
