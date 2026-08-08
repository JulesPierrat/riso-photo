# riso-photo

Transformer une photographie en **jeu de calques monochromes** prêts pour l'impression risographique.

Une risographe n'imprime qu'une encre à la fois : un visuel en trois couleurs, c'est trois passages machine, donc trois fichiers en niveaux de gris, un par encre. `riso-photo` automatise cette **séparation**. À partir d'une photo et d'un profil d'impression décrit en JSON, il produit :

- **les calques**, un par encre, tramés et prêts à partir en machine ;
- **un aperçu** simulant le rendu du tirage final, encres semi-transparentes et couleur du papier comprises ;
- **un `todo.md`** qui indique quoi imprimer, dans quel ordre et avec quels réglages.

Les encres sont libres : rose fluo, bleu, jaune, vert, noir — pas seulement du CMJN. C'est ce que permet la méthode de séparation par défaut, décrite dans [`doc/separation.md`](doc/separation.md).

> **État du projet — v0.3.** Les calques partent directement en machine : séparations `luminance`, `duotone`, `tritone` et `density-lsq`, tramage AM et FM, aperçu, rapports. Restent les repères de calage et la méthode `cmyk`. Voir [`doc/roadmap.md`](doc/roadmap.md).

---

## Installation

Prérequis : **Python 3.10 ou plus**.

```bash
git clone git@github.com:JulesPierrat/riso-photo.git
cd riso-photo

python3 -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate

pip install -r requirements.txt
```

Deux dépendances seulement : `Pillow` (lecture/écriture image) et `NumPy` (calcul pixel). Le solveur de séparation est intégré.

Vérifier que tout répond :

```bash
python riso-photo.py --help
```

---

## Premier tirage

### 1. Créer le projet

Un projet est un simple dossier dans `project/`, portant le nom du travail :

```bash
mkdir -p project/portrait-anna
```

### 2. Déposer la photo

Une seule image dans ce dossier, en `.jpg`, `.png` ou `.tif` :

```
project/portrait-anna/
└── source.jpg
```

S'il y a plusieurs images, celle nommée `source.*` l'emporte ; sinon le programme s'arrête et demande de lever l'ambiguïté.

### 3. Choisir un profil

Les profils vivent dans `config/`. Ils décrivent les encres, le papier et les réglages d'impression — jamais l'image, ce qui les rend réutilisables d'une photo à l'autre.

```bash
ls config/
# duotone-rose-noir.json  mono-noir.json  trichro-cmj.json
```

Prendre le plus proche du matériel disponible, quitte à l'adapter ensuite. Le champ le plus important est la couleur de chaque encre : la référence complète est dans [`doc/config.md`](doc/config.md).

### 4. Lancer

```bash
python riso-photo.py portrait-anna -c duotone-rose-noir
```

### 5. Récupérer les fichiers

```
project/portrait-anna/output/
├── 01_fluo-pink.png    ← passage 1
├── 02_black.png        ← passage 2
├── preview.png         ← simulation du rendu final
├── todo.md             ← plan d'impression
└── run.json            ← paramètres utilisés, pour reproduire le tirage
```

Ouvrir `preview.png` pour juger le résultat, puis `todo.md` pour imprimer.

⚠️ **Chaque run écrase intégralement `output/`.** Il n'y a pas d'historique. Tout ce qui doit survivre — la photo source, des notes, des retouches manuelles — se range à la racine du projet, qui n'est jamais touchée.

---

## Régler le résultat

Le rendu ne tombe presque jamais juste du premier coup. Dans l'ordre :

**Itérer sur les tons.** `--preview-only` saute les calques et le tramage pour ne produire que l'aperçu — quelques secondes au lieu d'une minute. C'est le mode dans lequel on ajuste la section `tone` du profil (contraste, point noir, gamma). La risographe écrase les ombres et délave les hautes lumières ; un contraste à `0.15` et un point noir non nul compensent presque toujours.

```bash
python riso-photo.py portrait-anna -c duotone-rose-noir --preview-only
```

**Vérifier avant de produire.** `--dry-run` affiche le plan d'impression et les avertissements sans rien écrire.

**Monter en résolution pour le tramage.** En trame classique (`clustered-dot`), sortir à 300 dpi ne laisse qu'une trentaine de niveaux de gris et fait apparaître des bandes dans les dégradés. Passer à 600 dpi :

```bash
python riso-photo.py portrait-anna -c duotone-rose-noir --dpi 600
```

Le détail de cette contrainte est dans [`doc/halftone.md`](doc/halftone.md).

**Puis imprimer un essai.** Aucune simulation écran ne rend les encres fluo, qui sortent du gamut sRVB. L'aperçu sert à valider la structure de la séparation ; la couleur se cale sur papier.

Toutes les options sont dans [`doc/cli.md`](doc/cli.md).

---

## Documentation

La spécification technique complète est dans [`doc/`](doc/README.md) :

| | |
|---|---|
| [architecture.md](doc/architecture.md) | Modules, pipeline de traitement, conventions internes. |
| [cli.md](doc/cli.md) | Référence de la ligne de commande. |
| [config.md](doc/config.md) | Référence du profil JSON, champ par champ. |
| [separation.md](doc/separation.md) | Modèle colorimétrique et méthodes de séparation. |
| [halftone.md](doc/halftone.md) | Tramage, linéature, angles, moiré. |
| [sorties.md](doc/sorties.md) | Fichiers produits et conventions. |
| [plan.md](doc/plan.md) | Plan d'implémentation : contrats, lots, tests, risques. |
| [roadmap.md](doc/roadmap.md) | État d'avancement et jalons. |
