# Séparation

C'est le cœur du programme : transformer une image RVB en `N` cartes de couverture d'encre qui, une fois surimprimées, se rapprochent le plus possible de l'original.

## Le problème

Une risographe n'imprime qu'une encre par passage, et ces encres sont **semi-transparentes**. Superposer du rose fluo et du bleu ne donne pas « rose puis bleu » mais une troisième couleur issue du filtrage successif de la lumière par les deux couches d'encre sur le papier.

La séparation est donc un problème inverse : connaissant la couleur cible de chaque pixel et les couleurs des encres disponibles, trouver les couvertures `a₁ … a_N ∈ [0, 1]` qui reproduisent au mieux cette cible une fois mélangées.

Difficulté supplémentaire : les jeux d'encres riso sont arbitraires. Rien ne garantit qu'on dispose de cyan, magenta et jaune — un profil courant est « rose fluo + bleu + noir ». Les algorithmes de séparation quadrichromique classiques ne s'appliquent pas directement.

## Le modèle colorimétrique

### Surimpression

Chaque couche d'encre se comporte comme un filtre partiellement transparent posé sur le papier. Le modèle multiplicatif :

```
Rendu = Couleur_papier × Π (1 − aᵢ · opacitéᵢ · (1 − Couleurᵢ))
```

où `aᵢ` est la couverture de l'encre `i` et `Couleurᵢ` sa couleur en aplat. À `aᵢ = 0`, le facteur vaut 1 : l'encre est absente. À `aᵢ = 1` et `opacité = 1`, le facteur vaut `Couleurᵢ` : l'encre filtre pleinement.

C'est ce modèle qui produit `preview.png`.

**Ce calcul se fait obligatoirement en espace linéaire.** Appliqué sur des valeurs sRVB encodées en gamma, il donne des mélanges visiblement faux — typiquement des superpositions trop claires. C'est l'erreur la plus fréquente sur ce type d'outil.

### Passage en densité

Le modèle ci-dessus est multiplicatif, donc non linéaire en `a` — désagréable à inverser. Le logarithme le rend additif. En posant la densité :

```
D = −log₁₀(RVB_linéaire)
```

la superposition devient une somme :

```
D_cible = D_papier + Σ aᵢ · Dᵢ
```

où `Dᵢ = −log₁₀(Couleurᵢ)` est la densité de l'encre `i` à 100 %, un vecteur à 3 composantes (R, V, B).

C'est un **système linéaire en `a`**, ce qui ouvre l'accès aux moindres carrés. Toute la méthode `density-lsq` repose là-dessus.

En pratique on borne les valeurs linéaires par le bas (typiquement `1e-4`) avant le logarithme, sinon un noir pur donne une densité infinie.

---

## Les méthodes

### `luminance` — 1 encre

Inversion directe du modèle de surimpression. Le rendu d'une couverture `a` vaut `Papier × (1 − a·(1 − T))`, où `T` est la transmittance de l'aplat ; on résout en luminance :

```
a = (1 − Y_cible / Y_papier) / (1 − T_Y)
```

Ce n'est **pas** `1 − luminance perceptuelle`, qui serait le réflexe naturel : sur un gris moyen, cette formule donnerait 50 % de couverture là où le modèle en réclame près de 80 %, et le tirage sortirait très délavé. Surtout, l'aperçu cesserait de correspondre au calque, puisqu'il applique le même modèle dans l'autre sens.

La formule tient compte de la couleur du papier et de celle de l'encre : sur crème, un blanc de la photo reste du papier nu ; avec une encre claire, `1 − T_Y` est petit et la couverture sature vite — une encre jaune ne peut pas produire d'ombres, et le calcul le reflète.

Sans réglage, mais c'est la référence pour juger si un duotone apporte vraiment quelque chose.

### `duotone` / `tritone` — 2 à 3 encres, par plages tonales

Chaque encre reçoit une courbe de réponse sur la luminance, définie dans `separation.curves` (voir [config.md](config.md)). L'encre claire prend typiquement les demi-teintes et les hautes lumières, l'encre foncée les ombres, avec une zone de recouvrement où les deux se mélangent.

**Cette méthode ignore délibérément la chromie de la photo.** Ce n'est pas une reproduction, c'est un parti pris graphique : une photo de ciel bleu séparée en rose/noir donnera un ciel rose. C'est exactement ce qu'on cherche la plupart du temps en riso, et c'est le mode qui donne les résultats les plus caractéristiques sur un portrait.

Le réglage se fait entièrement dans les courbes. C'est la méthode la plus manuelle et la plus expressive.

### `cmyk` — jeux d'encres proches de cyan / magenta / jaune / noir

Séparation quadrichromique classique : passage en CMJ, extraction du noir avec GCR paramétrable par `black_generation`, puis mappage de chaque canal sur l'encre riso la plus proche.

Pertinente uniquement si le jeu d'encres est effectivement proche du CMJN. Sur des encres arbitraires, le mappage devient une approximation grossière et `density-lsq` fait mieux.

### `density-lsq` — N encres arbitraires (défaut)

La méthode générale, celle qui justifie l'existence du programme : elle gère n'importe quel jeu d'encres.

**Formulation.** On construit la matrice `M` de taille `3 × N` dont la colonne `i` est la densité `Dᵢ` de l'encre `i`. Pour chaque pixel de densité cible `D_cible`, on cherche le vecteur de couvertures `a` qui minimise :

```
‖ M · a − (D_cible − D_papier) ‖²     sous contrainte  0 ≤ aᵢ ≤ min(1, max_coverageᵢ)
```

C'est un problème de moindres carrés à bornes, résolu par NNLS bornée. Le résultat `a` **est** directement le jeu de calques.

**Implémentation.** SciPy fournit le solveur (`scipy.optimize.nnls` ou `lsq_linear`). En son absence, on retombe sur un solveur par projection intégré : moindres carrés non contraints, projection sur les bornes, quelques itérations de raffinement du résidu. Moins exact, suffisant en pratique.

Le calcul se vectorise sur toute l'image plutôt que pixel par pixel — sans quoi une photo de 8 mégapixels devient inexploitable.

**Pondération perceptuelle.** L'erreur est pondérée par canal pour se rapprocher de la sensibilité de l'œil, plutôt que de traiter R, V et B à égalité. Une erreur dans le vert se voit davantage qu'une erreur dans le bleu.

**Sous-détermination.** Avec 4 encres ou plus, le système a plus d'inconnues que d'équations : plusieurs combinaisons donnent la même couleur. `black_generation` sert de régularisation, en privilégiant l'encre la plus foncée pour les zones neutres — ce qui économise de l'encre et facilite le repérage.

---

## Limitation d'encrage

Deux plafonds, appliqués après la séparation :

1. **`max_coverage` par encre** — écrêtage simple de chaque carte.
2. **`total_ink_limit` sur la somme** — quand `Σ aᵢ` dépasse la limite, on ne coupe pas brutalement, ce qui produirait des aplats plats et des cassures visibles dans les ombres. On réduit les encres claires d'un facteur `f` et on compense par l'encre la plus foncée, qui apporte le plus de densité par unité de couverture. La densité perçue est à peu près conservée alors que l'encrage total redescend.

En notant `D` les densités perçues, `S` la somme des couvertures claires et `c = Σ aⱼ·Dⱼ / D_foncée` leur équivalent en encre foncée, `f` est la solution de `f·S + a_foncée + (1 − f)·c = limite`, soit :

```
f = (limite − a_foncée − c) / (S − c)
```

Deux cas dégénérés retombent sur une réduction uniforme de tous les calques : des encres de densités trop proches, où le transfert ne gagne rien (`S ≈ c`), et une limite plus basse que la couverture de l'encre foncée seule, où il n'y a rien à reporter. L'invariant `Σ aᵢ ≤ limite`, lui, est garanti dans tous les cas.

Le seuil de `preserve_highlights` est fixé à 2 % de couverture : en dessous, une trame ne dépose qu'un point isolé par cellule, qui salit les blancs sans apporter de nuance.

La couverture réellement atteinte, moyenne et maximale, est mesurée et reportée dans le `todo.md` — pour vérifier avant impression que le plafond n'a pas été atteint sur une portion significative de l'image.

---

## Limites du modèle

À connaître pour savoir quand ne pas faire confiance à l'aperçu.

- **Diffusion optique ignorée.** La lumière entre dans le papier, diffuse latéralement et ressort à côté du point d'encre : les trames paraissent plus denses qu'elles ne le sont géométriquement (effet Yule-Nielsen). Le rendu réel est donc légèrement plus foncé que la simulation, surtout dans les demi-teintes.
- **Interactions physiques ignorées.** Une encre déposée sur une encre encore humide n'adhère pas comme sur du papier nu. Le modèle traite les couches comme indépendantes.
- **Fluorescence non modélisable.** Les encres fluo réémettent de la lumière et sortent du gamut sRVB. Aucune simulation écran ne peut les représenter : l'aperçu les sous-estimera toujours.
- **Linéarité de la densité approximative.** L'additivité en espace densité est une approximation, bonne en couverture faible à moyenne, moins fiable près de 100 %.

Conséquence pratique : l'aperçu sert à valider la **structure** de la séparation — répartition tonale, contraste, quelle encre porte quoi. Pour la couleur exacte, rien ne remplace un tirage d'essai. Le rôle des courbes `tone` est justement de rattraper l'écart une fois cet essai en main.
