# Plan d'implémentation

Découpage du développement en lots livrables. Chaque lot a un objectif vérifiable, des contrats d'interface fixés à l'avance et un critère de fin explicite.

Pour la vue produit — jalons et pistes ultérieures — voir [roadmap.md](roadmap.md).

---

## Principes de découpage

**Un tirage papier le plus tôt possible.** Tout le programme repose sur la valeur `color` de chaque encre, qui ne peut être calée que sur un tirage réel. Les lots 1 à 5 visent donc la chaîne complète la plus courte possible — une séparation naïve mais des fichiers imprimables — avant toute sophistication. Un `density-lsq` parfait calé sur des couleurs d'encre fausses ne sert à rien.

**L'aperçu avant la séparation générale.** Sans `preview.png`, impossible de juger si une séparation est juste. Développer `density-lsq` avant l'aperçu, ce serait travailler à l'aveugle sur l'algorithme le plus délicat du projet.

**Les contrats avant le code.** Les signatures ci-dessous sont fixées maintenant. Chaque module doit pouvoir être écrit et testé sans que les suivants existent.

**Chaque lot laisse le programme fonctionnel.** Jamais d'état intermédiaire cassé : un lot qui n'est pas fini se termine par une erreur explicite « méthode non implémentée », pas par un plantage.

---

## Contrats des modules

Fixés avant écriture. Toute image intermédiaire est un `numpy.float32` dans `[0, 1]`, en espace **linéaire** ; les couvertures valent `1.0` pour l'encre pleine. Voir les conventions dans [architecture.md](architecture.md).

### `src/errors.py`

```python
class RisoError(Exception):          code = 3
class UsageError(RisoError):         code = 1   # projet/profil introuvable, source ambiguë
class ProfileError(RisoError):       code = 2   # validation du JSON, porte tous les problèmes
class NotImplementedYet(RisoError):  code = 3   # lot en cours, message explicite
```

### `src/color.py`

```python
def parse_hex(value: str) -> str                 # normalise en "#RRGGBB"
def hex_to_srgb(value: str) -> np.ndarray        # (3,) sRVB encodé
def hex_to_linear(value: str) -> np.ndarray      # (3,) linéaire, lecture seule
def srgb_to_linear(a: np.ndarray) -> np.ndarray
def linear_to_srgb(a: np.ndarray) -> np.ndarray
```

Module sans dépendance vers le reste de `src/`. Les conversions sRVB étaient initialement prévues dans `image.py` et le parsing hexadécimal dans `inks.py`, mais `config.py` a besoin des deux dès le lot 1 — les laisser là aurait créé un cycle `config` → `inks` → `config`. `image.py` et `inks.py` s'appuient dessus.

### `src/config.py`

```python
@dataclass(frozen=True)
class Ink:
    name: str; label: str
    color: np.ndarray        # (3,) sRVB linéaire
    order: int; opacity: float
    screen_angle: float; max_coverage: float

@dataclass(frozen=True)
class Profile:
    name: str; description: str
    inks: tuple[Ink, ...]    # triées par `order`
    paper: Paper
    separation: SeparationCfg
    tone: ToneCfg
    halftone: HalftoneCfg
    output: OutputCfg
    warnings: tuple[str, ...]
    sources: tuple[str, ...] # traçabilité : fichiers et surcharges appliqués

def resolve_config_path(spec: str) -> Path
def load_profile(spec: str, *, project_dir: Path | None = None,
                 overrides: dict | None = None) -> Profile
```

`load_profile` enchaîne : lecture JSON → fusion profonde du `config.json` local s'il existe → application des surcharges CLI → valeurs par défaut → validation → gel. Lève `ProfileError` avec **tous** les champs fautifs listés, pas seulement le premier.

### `src/project.py`

```python
@dataclass(frozen=True)
class Project:
    name: str; root: Path; source: Path; output_dir: Path

def resolve_project(name: str, base: Path = Path("project")) -> Project
def find_source(root: Path) -> Path
def prepare_output(project: Project) -> None
```

`prepare_output` refuse de vider un `output/` non vide qui ne contient pas de `run.json` — signature d'un dossier produit par le programme.

### `src/image.py`

```python
def load_linear(path: Path) -> np.ndarray            # (H, W, 3)
def source_size(path: Path) -> tuple[int, int]       # sans décoder les pixels
def target_long_edge_px(long_edge_mm: float, dpi: int) -> int
def resize_to(img: np.ndarray, long_edge_px: int) -> np.ndarray
def resolution_warning(source_px: int, target_px: int) -> str | None
def relative_luminance(img: np.ndarray) -> np.ndarray  # (H, W) Y linéaire
def luminance(img: np.ndarray) -> np.ndarray           # (H, W) échelle perceptuelle
def tone_curve(x: np.ndarray, cfg: ToneCfg) -> np.ndarray   # courbe de référence
def apply_tone(img: np.ndarray, cfg: ToneCfg) -> np.ndarray
```

`luminance` rend une échelle **perceptuelle**, où le gris moyen vaut ~0.5 : c'est elle que prennent en entrée les courbes de réponse `duotone` / `tritone`, dont les points de contrôle seraient illisibles sur une échelle linéaire. `relative_luminance` donne le Y linéaire, utilisé pour les mélanges.

### `src/inks.py`

```python
def transmittance(ink: Ink) -> np.ndarray            # (3,) filtrage d'un aplat 100 %
def to_density(linear: np.ndarray, floor: float = 1e-4) -> np.ndarray
def from_density(d: np.ndarray) -> np.ndarray
def ink_density(ink: Ink) -> np.ndarray              # (3,)
def density_matrix(inks: Sequence[Ink]) -> np.ndarray # (3, N)
def luminance_density(inks: Sequence[Ink]) -> np.ndarray  # (N,) densité perçue
```

### `src/separation.py`

```python
def separate(img: np.ndarray, profile: Profile) -> tuple[np.ndarray, dict]  # (N, H, W)
def apply_curve(x: np.ndarray, points: list[list[float]]) -> np.ndarray
def limit_ink(cov: np.ndarray, profile: Profile) -> tuple[np.ndarray, dict]
```

`separate` dispatche sur `profile.separation.method` et applique `limit_ink` en fin de course. Le `dict` porte les statistiques d'encrage (`total_ink_max`, `total_ink_mean`, `limited_fraction`) destinées au rapport : elles ne sont connues qu'ici et seraient impossibles à recalculer ensuite — d'où le tuple, là où le contrat initial ne rendait que le tableau.

### `src/halftone.py`

```python
def halftone(cov: np.ndarray, cfg: HalftoneCfg,
             angle_deg: float, dpi: int) -> np.ndarray   # binaire {0., 1.}
def check_angles(inks: Sequence[Ink]) -> list[str]       # avertissements
```

### `src/preview.py`

```python
def composite(cov: np.ndarray, profile: Profile) -> np.ndarray   # (H, W, 3) linéaire
```

### `src/output.py`

```python
def add_margin_and_marks(a: np.ndarray, cfg: OutputCfg, dpi: int) -> np.ndarray
def write_layer(cov: np.ndarray, path: Path, cfg: OutputCfg) -> None
def write_preview(rgb_linear: np.ndarray, path: Path) -> None
```

`write_layer` est le **seul** endroit du programme où `output.invert` est lu.

### `src/report.py`

```python
@dataclass(frozen=True)
class LayerStats:
    file: str; ink: str; order: int
    coverage_mean: float; coverage_max: float

def write_run_json(path: Path, project, profile, stats, meta) -> None
def render_todo(project, profile, stats, meta) -> str
```

### `src/cli.py`

```python
def build_parser() -> argparse.ArgumentParser
def main(argv: list[str] | None = None) -> int
```

`main` attrape `RisoError` et retourne `err.code`. Aucune trace Python ne doit remonter à l'utilisateur sur une erreur prévue.

---

## Les lots

### Lot 0 — Socle

| | |
|---|---|
| **Objectif** | Le squelette tourne et les tests s'exécutent. |
| **Fichiers** | `riso-photo.py`, `src/__init__.py`, `src/errors.py`, `tests/`, `.gitignore` |
| **Taille** | ~50 lignes |

`riso-photo.py` se limite à `from src.cli import main; sys.exit(main())`. Hiérarchie d'exceptions avec leur code de sortie.

**Fin de lot** — `python riso-photo.py --help` affiche l'aide et `pytest` passe à vide.

---

### Lot 1 — Projet et profil

| | |
|---|---|
| **Objectif** | Résoudre un projet et un profil, valider, afficher — sans toucher aux pixels. |
| **Fichiers** | `src/color.py`, `src/project.py`, `src/config.py`, `src/cli.py`, `config/mono-noir.json`, `config/duotone-rose-noir.json` |
| **Dépend de** | Lot 0 |
| **Taille** | ~350 lignes |

Le gros du travail est la validation : toutes les règles de [config.md](config.md), erreurs bloquantes **et** avertissements accumulés. C'est le module le plus long du projet et le plus rentable à tester — chaque règle non vérifiée ici devient un plantage obscur trois étapes plus loin.

Les deux premiers profils sont écrits maintenant parce qu'ils servent de fixtures aux tests.

La fusion du `config.json` local au projet, initialement prévue au lot 8, est faite ici : douze lignes, et cela évite de laisser le paramètre `project_dir` de `load_profile` sans effet.

**Fin de lot** — `python riso-photo.py demo -c duotone-rose-noir --dry-run` affiche le profil résolu et ses avertissements. Un JSON fautif produit la liste complète des erreurs et le code `2`. Un projet inexistant liste les projets disponibles et retourne `1`.

---

### Lot 2 — Chaîne image

| | |
|---|---|
| **Objectif** | Charger, linéariser, redimensionner, corriger les tons. |
| **Fichiers** | `src/image.py` |
| **Dépend de** | Lot 1 (pour `ToneCfg`) |
| **Taille** | ~150 lignes |

Point de vigilance : la conversion sRVB ↔ linéaire doit utiliser la vraie courbe sRVB (segment linéaire sous 0.04045, puis puissance 2.4), pas un gamma 2.2 approché. L'écart se voit dans les basses lumières, exactement là où la riso est déjà fragile.

Deux étapes passent par une table de correspondance plutôt que par un calcul par pixel : la conversion 8 bits → linéaire au chargement (256 entrées, exactes) et la courbe tonale (8192 entrées). Sur les 37 Mpx d'un A4 à 600 dpi — le réglage recommandé, donc le cas courant — la chaîne complète passe d'environ 8 s à 2 s, dont 1,4 s de rééchantillonnage.

**Fin de lot** — aller-retour sRVB → linéaire → sRVB à moins de `1e-6`. Redimensionnement respectant le ratio. `apply_tone` avec les valeurs par défaut est l'identité — un profil sans section `tone` ne doit rien changer. La table tonale reste à moins d'un demi-niveau 8 bits de la courbe exacte.

---

### Lot 3 — Encres et premières séparations

| | |
|---|---|
| **Objectif** | Produire les cartes de couverture en `luminance` et `duotone`. |
| **Fichiers** | `src/inks.py`, `src/separation.py` (partiel) |
| **Dépend de** | Lots 1, 2 |
| **Taille** | ~200 lignes |

`inks.py` inclut le passage en densité, utilisé par `luminance` et `duotone` seulement à la marge — mais il est écrit ici en entier, testé isolément, parce que le lot 6 en dépendra entièrement.

`limit_ink` est implémenté dès ce lot avec sa redistribution vers l'encre la plus foncée, décrite dans [separation.md](separation.md).

`tritone`, prévu au lot 8, arrive ici : il partage intégralement le code de `duotone` — une courbe de réponse par encre — et ne coûte que le test. Restent `cmyk` et `density-lsq`, qui lèvent une erreur explicite « non implémentée ».

**Fin de lot** — une image de test donne `N` cartes de couverture dans `[0, 1]`, aux bonnes dimensions, dont la somme respecte `total_ink_limit`. La méthode `luminance` inverse effectivement le modèle : réappliquer la surimpression au calque redonne la luminance de la source.

---

### Lot 4 — Aperçu et écriture

| | |
|---|---|
| **Objectif** | Premier run de bout en bout produisant des fichiers. |
| **Fichiers** | `src/preview.py`, `src/output.py` |
| **Dépend de** | Lot 3 |
| **Taille** | ~180 lignes |

Sortie en ton continu uniquement — pas de tramage, pas de repères, pas de marges. Le but est d'obtenir des PNG regardables.

`run.json` est écrit dès ce lot, par `report.py`, alors que le reste des rapports attend le lot 5 : sa présence est la signature qui autorise `prepare_output` à vider le dossier. Sans lui, un deuxième run refuserait d'écraser le premier et le comportement d'écrasement annoncé dans [cli.md](cli.md) ne tiendrait pas.

**Fin de lot** — `python riso-photo.py demo -c duotone-rose-noir` écrit `01_*.png`, `02_*.png` et `preview.png`. Un profil à une seule encre noire sur papier blanc donne un `preview.png` visuellement identique à la source désaturée : c'est le test de bout en bout du modèle colorimétrique.

---

### Lot 5 — Rapports · **jalon v0.1**

| | |
|---|---|
| **Objectif** | `todo.md`. La chaîne minimale est complète. |
| **Fichiers** | `src/report.py` (complété) |
| **Dépend de** | Lot 4 |
| **Taille** | ~150 lignes |

Le `todo.md` est rendu à partir des statistiques réelles du run, selon la spécification de [sorties.md](sorties.md). `run.json` a déjà été livré au lot 4, dont il conditionnait le comportement d'écrasement.

**Fin de lot** — un run produit les cinq fichiers attendus. **C'est le moment d'imprimer.** Le tirage d'essai sert à corriger les `color` des profils, et rien ne devrait avancer avant cette validation physique.

---

### Lot 6 — Séparation générale

| | |
|---|---|
| **Objectif** | `density-lsq` : jeux d'encres arbitraires. |
| **Fichiers** | `src/separation.py` (complété), `config/trichro-cmj.json` |
| **Dépend de** | Lot 5 et un tirage d'essai |
| **Taille** | ~150 lignes |

Le module techniquement le plus délicat. Moindres carrés bornés sur `M · a = D_cible − D_papier`.

Deux exigences non négociables :

- **Vectorisation.** Le solveur tourne sur tous les pixels d'un coup, jamais dans une boucle Python. Une photo de 8 mégapixels traitée pixel par pixel prendrait des heures.
- **Pondération perceptuelle** par canal, sans quoi les erreurs dans le bleu pèsent autant que dans le vert.

Le plan prévoyait `scipy.optimize.lsq_linear` avec repli intégré. Ce contrat est infaisable : `lsq_linear` traite **un** problème à la fois et ne se vectorise pas. La solution retenue — énumération des 3^N jeux de contraintes actives, exacte et entièrement vectorisée — est décrite dans [separation.md](separation.md). SciPy passe du chemin critique aux tests, où il sert de référence indépendante : un contrôle plus sévère qu'un repli, puisqu'il vérifie l'optimalité et pas seulement l'absence de plantage. SciPy n'est donc plus une dépendance d'exécution.

**Fin de lot** — sur un jeu d'encres proche du CMJ, `density-lsq` reproduit une mire de couleurs avec une erreur moyenne inférieure à celle de `duotone`. Temps de traitement sous 30 s pour 8 mégapixels. Le solveur ne fait jamais moins bien que `scipy.optimize.lsq_linear` sur des systèmes tirés au hasard.

---

### Lot 7 — Tramage · **jalon v0.3**

| | |
|---|---|
| **Objectif** | Fichiers directement exploitables en machine. |
| **Fichiers** | `src/halftone.py` |
| **Dépend de** | Lot 6 |
| **Taille** | ~250 lignes |

Les trois méthodes de [halftone.md](halftone.md), `check_angles`, l'avertissement sur le rapport `dpi / lpi`, et l'option `--preview-halftoned`.

`error-diffusion` est séquentiel par nature : l'écrire d'abord en NumPy ligne par ligne, et n'optimiser que si le temps de traitement devient gênant.

**Fin de lot** — un aplat à 50 % tramé puis moyenné redonne 50 % à 2 % près, pour les trois méthodes. Deux encres à 15° et 45° ne produisent pas de moiré visible sur un dégradé. `check_angles` avertit bien pour une paire à 5° et 95°, qui sont le même angle.

---

### Lot 8 — Finitions · **jalon v0.4**

| | |
|---|---|
| **Objectif** | Tout ce que la spécification promet encore. |
| **Fichiers** | `src/output.py` (complété), `src/separation.py`, `config/quadri-riso.json` |
| **Dépend de** | Lot 7 |
| **Taille** | ~250 lignes |

Marges et repères de calage, méthode `cmyk`, options CLI restantes (`--out`, `--preview-halftoned`).

**Fin de lot** — les repères tombent au pixel près à la même position sur tous les calques. C'est le seul critère qui compte : un décalage d'un pixel entre deux calques rend les repères inutilisables pour caler la machine.

---

## Stratégie de test

Les tests s'exécutent avec `python3 -m pytest` depuis la racine du dépôt. Dépendances de développement dans `requirements-dev.txt`.

**Fixtures synthétiques, pas de binaire dans le repo.** `tests/fixtures/make_fixtures.py` génère de façon déterministe une image de test : rampe de luminance horizontale, mire de couleurs primaires et secondaires, plage de tons chair, aplats noir et blanc purs. Petite, reproductible, et couvrant les cas où les erreurs de colorimétrie se voient.

**Ce qui se teste automatiquement**

| Cible | Approche |
|---|---|
| `config.py` | Une règle de validation = un test. Le module le plus densément couvert. |
| `image.py` | Aller-retours numériques, invariants de dimensions, identité de `apply_tone` par défaut. |
| `inks.py` | `to_density` / `from_density` réciproques, densité d'une encre connue. |
| `separation.py` | Bornes `[0, 1]`, respect de `total_ink_limit`, cas dégénérés (image blanche, image noire). |
| `halftone.py` | Conservation de la densité moyenne, sortie strictement binaire. |
| `report.py` | Rendu du `todo.md` sur un jeu de statistiques figé. |
| CLI | Codes de sortie sur chaque cas d'erreur. |

**Ce qui ne se teste pas automatiquement** — la justesse visuelle d'une séparation, la fidélité de l'aperçu, le rendu d'une trame à l'impression. Ces points passent par le tirage d'essai du lot 5, puis par une planche de contrôle à chaque changement du modèle colorimétrique.

**Test de non-régression de bout en bout** — un run complet sur la fixture avec un profil figé, dont on compare les sommes de contrôle des fichiers produits. Il attrape les régressions silencieuses que les tests unitaires laissent passer.

---

## Risques

**La valeur `color` des encres est le maillon faible.** Tout le modèle en dépend, et les chartes constructeur sont des approximations écran. Sans tirage d'essai, la justesse plafonne quels que soient les algorithmes. C'est la raison d'être du jalon v0.1 au lot 5, et ce qui rendrait la calibration par nuancier scanné (voir [roadmap.md](roadmap.md)) plus rentable que n'importe quel raffinement du solveur.

**Performance de `density-lsq`.** Un solveur non vectorisé rend le programme inutilisable sur des photos réelles. À traiter comme une contrainte de conception au lot 6, pas comme une optimisation ultérieure.

**Mélanges en espace non linéaire.** L'erreur classique de ce type d'outil, et elle est silencieuse : le résultat paraît plausible tout en étant faux. La conversion en linéaire au chargement, une fois pour toutes, est la parade — d'où sa place dès le lot 2.

**Empilement des approximations.** Diffusion optique, interactions entre encres humides, fluorescence hors gamut : chacune est acceptable isolément, leur cumul peut écarter sensiblement l'aperçu du tirage. À surveiller sur les premières planches, quitte à introduire une correction Yule-Nielsen si l'écart gêne.

---

## Récapitulatif

| Lot | Contenu | Dépend de | Taille | Jalon |
|---|---|---|---|---|
| 0 | Socle, erreurs, tests | — | ~50 | |
| 1 | Projet, profil, validation | 0 | ~350 | |
| 2 | Chaîne image, tons | 1 | ~150 | |
| 3 | Encres, `luminance`, `duotone` | 1, 2 | ~200 | |
| 4 | Aperçu, écriture | 3 | ~180 | |
| 5 | `todo.md`, `run.json` | 4 | ~200 | **v0.1** |
| 6 | `density-lsq` | 5 + tirage | ~150 | **v0.2** |
| 7 | Tramage | 6 | ~250 | **v0.3** |
| 8 | Repères, `cmyk`, `tritone` | 7 | ~250 | **v0.4** |

Environ 1 800 lignes hors tests. La validation du profil et le tramage concentrent le volume ; `density-lsq`, court, concentre la difficulté.
