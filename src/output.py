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
