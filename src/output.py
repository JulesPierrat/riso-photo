"""Écriture des fichiers.

Seul endroit du programme qui connaît `output.invert` : partout ailleurs, une
couverture de `1.0` signifie encre pleine. Concentrer l'inversion ici évite les
erreurs de signe dans le reste de la chaîne.

Voir doc/sorties.md pour les conventions.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from .config import Ink, OutputCfg
from .color import linear_to_srgb
from .errors import RisoError

PREVIEW_FILENAME = "preview.png"

MM_PER_INCH = 25.4

#: Épaisseur du trait des repères, en millimètres. Assez fin pour caler à vue,
#: assez épais pour survivre au master.
_MARK_THICKNESS_MM = 0.15

#: Longueur d'un bras de croix, en fraction de la marge.
_MARK_ARM_RATIO = 0.35

#: Rayon du cercle, en fraction du bras. Le cercle donne une référence
#: continue, qui rend un décalage bien plus lisible qu'une croix seule.
_MARK_RADIUS_RATIO = 0.75


def mm_to_px(millimetres: float, dpi: int) -> int:
    return int(round(millimetres / MM_PER_INCH * dpi))


def _draw_mark(canvas: np.ndarray, row: int, column: int, arm: int, thickness: int) -> None:
    """Croix inscrite dans un cercle, à pleine encre."""
    half = thickness // 2
    height, width = canvas.shape

    top, bottom = max(0, row - half), min(height, row - half + thickness)
    left, right = max(0, column - half), min(width, column - half + thickness)

    canvas[top:bottom, max(0, column - arm) : min(width, column + arm + 1)] = 1.0
    canvas[max(0, row - arm) : min(height, row + arm + 1), left:right] = 1.0

    radius = max(2.0, arm * _MARK_RADIUS_RATIO)
    reach = int(np.ceil(radius)) + thickness

    rows = np.arange(max(0, row - reach), min(height, row + reach + 1))
    columns = np.arange(max(0, column - reach), min(width, column + reach + 1))
    if rows.size == 0 or columns.size == 0:
        return

    distance = np.hypot(
        (rows - row)[:, np.newaxis].astype(np.float32),
        (columns - column)[np.newaxis, :].astype(np.float32),
    )
    ring = np.abs(distance - radius) <= thickness / 2.0
    patch = canvas[rows[0] : rows[-1] + 1, columns[0] : columns[-1] + 1]
    patch[ring] = 1.0


def add_margin_and_marks(layer: np.ndarray, cfg: OutputCfg) -> np.ndarray:
    """Ajoute la marge blanche et, si demandé, les repères de calage.

    Les repères sont dessinés depuis la seule géométrie — jamais depuis le
    contenu du calque — ce qui garantit qu'ils tombent au pixel près à la même
    position sur tous les passages. C'est toute leur utilité : on superpose
    deux tirages à contre-jour et l'écart des croix donne la dérive de
    repérage, de l'ordre de 1 à 2 mm sur une risographe.

    Ils sont ajoutés **après** le tramage : un repère doit être un trait plein,
    pas une trame de points.
    """
    margin = mm_to_px(cfg.margin_mm, cfg.dpi)
    if margin <= 0:
        return layer

    height, width = layer.shape
    canvas = np.zeros((height + 2 * margin, width + 2 * margin), dtype=np.float32)
    canvas[margin : margin + height, margin : margin + width] = layer

    if cfg.registration_marks:
        arm = max(2, int(margin * _MARK_ARM_RATIO))
        thickness = max(1, mm_to_px(_MARK_THICKNESS_MM, cfg.dpi))
        centre = margin // 2
        for row in (centre, canvas.shape[0] - 1 - centre):
            for column in (centre, canvas.shape[1] - 1 - centre):
                _draw_mark(canvas, row, column, arm, thickness)

    return canvas


def layer_filename(ink: Ink, cfg: OutputCfg) -> str:
    """`01_fluo-pink.png`.

    Le préfixe numérique fait apparaître les fichiers dans l'ordre de passage
    dans n'importe quel explorateur : au moment d'imprimer, c'est la première
    chose qu'on veut lire sans réfléchir.
    """
    return f"{ink.order:02d}_{ink.name}.{cfg.format}"


def _quantize(values: np.ndarray, bit_depth: int) -> np.ndarray:
    """[0, 1] → entiers non signés, avec arrondi au plus proche."""
    if bit_depth == 16:
        return np.rint(np.clip(values, 0.0, 1.0) * 65535.0).astype(np.uint16)
    return np.rint(np.clip(values, 0.0, 1.0) * 255.0).astype(np.uint8)


def _save(img: Image.Image, path: Path, dpi: int) -> None:
    try:
        img.save(path, dpi=(dpi, dpi))
    except OSError as exc:
        raise RisoError(f"{path} : écriture impossible — {exc}") from exc


def write_layer(coverage: np.ndarray, path: Path, cfg: OutputCfg) -> None:
    """Écrit un calque en niveaux de gris.

    Par défaut, noir = 100 % d'encre : le calque se lit comme un tirage de
    l'encre en noir, ce qu'attendent la plupart des pilotes riso. `invert`
    produit des positifs inversés pour les prestataires qui les demandent.

    Toujours en niveaux de gris, jamais en RVB : un calque n'a pas de couleur,
    la couleur est l'encre chargée dans la machine.
    """
    coverage = add_margin_and_marks(coverage, cfg)
    values = coverage if cfg.invert else 1.0 - coverage
    quantized = _quantize(values, cfg.bit_depth)

    mode = "I;16" if cfg.bit_depth == 16 else "L"
    _save(Image.fromarray(quantized, mode=mode), path, cfg.dpi)


def write_preview(rgb_linear: np.ndarray, path: Path, cfg: OutputCfg) -> None:
    """Écrit l'aperçu, converti du linéaire vers le sRVB d'affichage.

    Toujours en 8 bits : c'est une image à regarder, pas un fichier de
    production.
    """
    encoded = _quantize(linear_to_srgb(rgb_linear), 8)
    _save(Image.fromarray(encoded, mode="RGB"), path, cfg.dpi)
