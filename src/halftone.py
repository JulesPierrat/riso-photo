"""Tramage : d'une couverture continue vers une carte binaire.

Une risographe ne sait déposer que de l'encre ou pas d'encre — le master est
perforé, chaque trou laisse passer. Tout dégradé passe donc par une trame.
Voir doc/halftone.md pour le choix des méthodes et des angles.

Les trois méthodes reposent sur le même principe : comparer la couverture à un
seuil qui varie dans l'espace. Ce qui les distingue est la façon dont ce seuil
est construit — grille inclinée, matrice ordonnée, ou masque stochastique.

Toutes sont **égalisées** : la proportion de pixels encrés vaut exactement la
couverture demandée. Sans cela la trame introduirait une dérive tonale, faible
mais systématique, qui décalerait toute l'image.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from .config import HalftoneCfg
from .errors import RisoError

#: Finesse de la table d'égalisation d'un point aggloméré.
_EQUALIZE_BINS = 4096

#: Résolution d'échantillonnage de la fonction de point, pour construire
#: cette table.
_SPOT_SAMPLES = 1024

#: Côté du masque bleu. 64 suffit à ne pas laisser voir de répétition, et se
#: construit en une fraction de seconde.
_BLUE_NOISE_SIZE = 64

#: Écart-type du noyau gaussien de la construction « vides et amas ».
_BLUE_NOISE_SIGMA = 1.9

#: Lignes traitées d'un coup. Borne la mémoire des grilles de coordonnées.
_CHUNK_ROWS = 512

#: Tolérances de détection du cas dégénéré « trame alignée sur la grille pixel
#: avec une cellule de taille entière », et décalage appliqué pour en sortir.
_ALIGNED_ANGLE_TOL = 1.0
_INTEGER_CELL_TOL = 0.02
_CELL_NUDGE = 1.005


# --------------------------------------------------------------------------
# Trame AM : points agglomérés sur grille inclinée


def _spot(u: np.ndarray, v: np.ndarray, shape: str) -> np.ndarray:
    """Fonction de point : petite au centre de la cellule, grande aux bords.

    Le seuil croît donc du centre vers l'extérieur, et le point grossit depuis
    le centre à mesure que la couverture augmente.
    """
    if shape == "line":
        return -np.cos(2.0 * np.pi * u)
    if shape == "square":
        return np.maximum(np.abs(u - 0.5), np.abs(v - 0.5))
    if shape == "ellipse":
        # Axes de poids inégaux : les points se raccordent d'abord dans un
        # sens, ce qui évite la cassure brutale des points ronds qui se
        # touchent tous ensemble aux alentours de 50 %.
        return -(np.cos(2.0 * np.pi * u) + 0.6 * np.cos(2.0 * np.pi * v))
    return -(np.cos(2.0 * np.pi * u) + np.cos(2.0 * np.pi * v))


@lru_cache(maxsize=8)
def _equalization(shape: str) -> tuple[float, float, np.ndarray]:
    """Table qui rend uniforme la répartition des seuils d'une fonction de point.

    La fonction de point brute n'est pas égalisée : demander 25 % de couverture
    n'encrerait pas 25 % de la surface. On tabule sa fonction de répartition,
    dont l'application transforme les seuils en une variable uniforme sur
    [0, 1] — la surface encrée devient alors exactement la couverture voulue.
    """
    axis = (np.arange(_SPOT_SAMPLES, dtype=np.float64) + 0.5) / _SPOT_SAMPLES
    u, v = np.meshgrid(axis, axis, indexing="ij")
    values = _spot(u, v, shape)

    low, high = float(values.min()), float(values.max())
    counts, _ = np.histogram(values, bins=np.linspace(low, high, _EQUALIZE_BINS + 1))
    cdf = np.cumsum(counts) / values.size

    return low, high, cdf.astype(np.float32)


def _deariased_cell(cell: float, angle_deg: float) -> float:
    """Écarte le cas où la trame échantillonne partout les mêmes positions.

    Quand la trame est alignée sur la grille pixel **et** que la cellule fait
    un nombre entier de pixels, toutes les cellules retombent exactement sur
    les mêmes points de la fonction de point. L'égalisation, calculée sur une
    répartition continue, ne correspond alors plus à ce petit échantillon
    discret : la gamme se décale, jusqu'à 4 % à 600 dpi et 60 lpi.

    Décaler la cellule d'un demi pour cent suffit à décorréler les phases et
    ramène l'écart sous 0.2 %. La linéature bouge de 0.3 lpi — invisible.

    Le cas ne se présente qu'aux angles 0° et 90°, que doc/halftone.md ne
    recommande que pour l'encre la plus claire d'un jeu de quatre.
    """
    aligned = min(angle_deg % 90.0, 90.0 - angle_deg % 90.0) < _ALIGNED_ANGLE_TOL
    integral = abs(cell - round(cell)) < _INTEGER_CELL_TOL
    return cell * _CELL_NUDGE if aligned and integral else cell


def clustered_dot(
    coverage: np.ndarray, lpi: int, dpi: int, angle_deg: float, shape: str = "round"
) -> np.ndarray:
    """Trame AM classique : points de taille variable sur une grille inclinée.

    C'est le rendu riso canonique. L'inclinaison est ce qui évite le moiré
    entre passages — voir `angle_spread` dans `config`.
    """
    height, width = coverage.shape
    cell = dpi / lpi
    if cell <= 1.0:
        raise RisoError(
            f"linéature trop fine : {lpi} lpi à {dpi} dpi ne laisse pas une "
            "cellule d'un pixel. Baisser `lpi` ou monter `dpi`."
        )

    cell = _deariased_cell(cell, angle_deg)

    angle = np.deg2rad(angle_deg)
    cos, sin = float(np.cos(angle)), float(np.sin(angle))
    low, high, cdf = _equalization(shape)
    span = (high - low) or 1.0

    columns = np.arange(width, dtype=np.float32)
    out = np.empty((height, width), dtype=np.float32)

    for start in range(0, height, _CHUNK_ROWS):
        stop = min(height, start + _CHUNK_ROWS)
        rows = np.arange(start, stop, dtype=np.float32)[:, np.newaxis]

        u = (cos * columns[np.newaxis, :] + sin * rows) / cell
        v = (-sin * columns[np.newaxis, :] + cos * rows) / cell

        values = _spot(u - np.floor(u), v - np.floor(v), shape)
        index = np.clip(
            ((values - low) / span * _EQUALIZE_BINS).astype(np.int32),
            0,
            _EQUALIZE_BINS - 1,
        )
        out[start:stop] = (coverage[start:stop] >= cdf[index]).astype(np.float32)

    return out


# --------------------------------------------------------------------------
# Trames à masque


@lru_cache(maxsize=8)
def bayer_matrix(size: int) -> np.ndarray:
    """Matrice de Bayer `size × size`, construite par récurrence."""
    matrix = np.zeros((1, 1), dtype=np.int64)
    while matrix.shape[0] < size:
        matrix = np.block(
            [
                [4 * matrix, 4 * matrix + 2],
                [4 * matrix + 3, 4 * matrix + 1],
            ]
        )
    return matrix


@lru_cache(maxsize=4)
def blue_noise_matrix(size: int = _BLUE_NOISE_SIZE) -> np.ndarray:
    """Masque de bruit bleu par la méthode « vides et amas » (Ulichney).

    On classe les positions du masque de sorte que, pour tout seuil, les points
    retenus soient répartis le plus uniformément possible — sans structure
    périodique. C'est ce qui donne un rendu granuleux sans moiré possible.

    Le procédé : partir d'un motif clairsemé, le rendre progressif en déplaçant
    l'amas le plus serré vers le vide le plus large jusqu'à stabilité, puis
    retirer les points un à un pour numéroter la première moitié du classement,
    et en ajouter un à un pour la seconde.
    """
    total = size * size
    kernel = _wrapped_gaussian(size, _BLUE_NOISE_SIGMA)

    rng = np.random.default_rng(0)
    pattern = np.zeros(total, dtype=bool)
    pattern[rng.choice(total, size=max(1, total // 10), replace=False)] = True
    pattern = pattern.reshape(size, size)

    energy = _energy(pattern, kernel)

    # Rendre le motif progressif : tant que déplacer l'amas le plus serré vers
    # le vide le plus large change quelque chose, c'est qu'il reste inégal.
    for _ in range(4 * total):
        cluster = _extreme(energy, pattern, tightest=True)
        pattern[cluster] = False
        energy -= _shifted(kernel, cluster)

        void = _extreme(energy, pattern, tightest=False)
        pattern[void] = True
        energy += _shifted(kernel, void)

        if void == cluster:
            break

    ranks = np.full((size, size), -1, dtype=np.int32)
    prototype = pattern.copy()
    placed = int(pattern.sum())

    # Première moitié : on retire, du plus aggloméré au plus isolé.
    for rank in range(placed - 1, -1, -1):
        cluster = _extreme(energy, pattern, tightest=True)
        pattern[cluster] = False
        energy -= _shifted(kernel, cluster)
        ranks[cluster] = rank

    # Seconde moitié : on ajoute, en comblant toujours le plus grand vide.
    pattern = prototype
    energy = _energy(pattern, kernel)
    for rank in range(placed, total):
        void = _extreme(energy, pattern, tightest=False)
        pattern[void] = True
        energy += _shifted(kernel, void)
        ranks[void] = rank

    return ranks


def _wrapped_gaussian(size: int, sigma: float) -> np.ndarray:
    """Noyau gaussien à bords cycliques, sans terme central.

    Le masque est destiné à être répété : mesurer les distances de façon
    cyclique évite un raccord visible entre tuiles.
    """
    steps = np.arange(size)
    distance = np.minimum(steps, size - steps).astype(np.float64)
    squared = distance[:, np.newaxis] ** 2 + distance[np.newaxis, :] ** 2
    kernel = np.exp(-squared / (2.0 * sigma**2))
    kernel[0, 0] = 0.0  # un point ne contribue pas à sa propre énergie
    return kernel


def _energy(pattern: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    energy = np.zeros(pattern.shape, dtype=np.float64)
    for position in zip(*np.nonzero(pattern)):
        energy += _shifted(kernel, position)
    return energy


def _shifted(kernel: np.ndarray, position: tuple[int, int]) -> np.ndarray:
    return np.roll(kernel, position, axis=(0, 1))


def _extreme(
    energy: np.ndarray, pattern: np.ndarray, *, tightest: bool
) -> tuple[int, int]:
    """Position de l'amas le plus serré (parmi les points) ou du plus grand
    vide (parmi les absences)."""
    if tightest:
        masked = np.where(pattern, energy, -np.inf)
        flat = int(np.argmax(masked))
    else:
        masked = np.where(pattern, np.inf, energy)
        flat = int(np.argmin(masked))
    return divmod(flat, energy.shape[1])


def _threshold_from_ranks(coverage: np.ndarray, ranks: np.ndarray) -> np.ndarray:
    """Applique un masque de rangs, répété sur toute l'image.

    Les rangs `0 … n−1` deviennent les seuils `1/n … 1` : à une couverture `a`,
    exactement la proportion `a` des positions passe, à l'arrondi du masque près.
    """
    size = ranks.shape[0]
    height, width = coverage.shape

    thresholds = ((ranks + 1) / ranks.size).astype(np.float32)
    tiled = np.tile(
        thresholds, ((height + size - 1) // size, (width + size - 1) // size)
    )[:height, :width]

    return (coverage >= tiled).astype(np.float32)


def bayer(coverage: np.ndarray, size: int = 8) -> np.ndarray:
    """Tramage ordonné. Motif régulier parfaitement visible — c'est le but."""
    return _threshold_from_ranks(coverage, bayer_matrix(size))


def blue_noise(coverage: np.ndarray) -> np.ndarray:
    """Trame FM stochastique. Aucune structure périodique, donc aucun moiré."""
    return _threshold_from_ranks(coverage, blue_noise_matrix())


# --------------------------------------------------------------------------
# Point d'entrée


def halftone(
    coverage: np.ndarray, cfg: HalftoneCfg, angle_deg: float, dpi: int
) -> np.ndarray:
    """Transforme une carte de couverture continue en carte binaire."""
    if cfg.method == "none":
        return coverage

    if cfg.method == "clustered-dot":
        return clustered_dot(coverage, cfg.lpi, dpi, angle_deg, cfg.dot_shape)
    if cfg.method == "bayer":
        return bayer(coverage, cfg.matrix_size)
    return blue_noise(coverage)
