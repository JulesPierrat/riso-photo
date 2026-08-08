"""Simulation du tirage : recompose les calques en une image RVB.

Applique le modèle de surimpression de doc/separation.md dans le sens direct,
là où la séparation l'a inversé :

    Rendu = Papier × Π (1 − aᵢ · (1 − Tᵢ))

où `Tᵢ` est la transmittance de l'aplat de l'encre `i`. C'est la même formule
des deux côtés — c'est ce qui garantit qu'un calque et son aperçu racontent la
même chose.

Sur ce que l'aperçu ne montre pas — fluorescence, diffusion optique du papier,
interactions entre encres humides — voir les limites du modèle dans
doc/separation.md.
"""

from __future__ import annotations

import numpy as np

from .config import Profile
from .inks import transmittance


def composite(coverage: np.ndarray, profile: Profile) -> np.ndarray:
    """Recompose `(N, H, W)` couvertures en `(H, W, 3)` linéaire.

    Le calcul se fait canal par canal et en place : sur un A4 à 600 dpi, une
    image RVB pèse déjà 440 Mo en float32, et matérialiser un facteur complet
    par encre doublerait la pointe mémoire pour rien.
    """
    height, width = coverage.shape[1:]
    out = np.empty((height, width, 3), dtype=np.float32)
    out[:] = profile.paper.color

    scratch = np.empty((height, width), dtype=np.float32)

    for ink, layer in zip(profile.inks, coverage):
        absorption = 1.0 - transmittance(ink)
        for channel in range(3):
            np.multiply(layer, absorption[channel], out=scratch)
            np.subtract(1.0, scratch, out=scratch)
            out[:, :, channel] *= scratch

    return np.clip(out, 0.0, 1.0, out=out)
