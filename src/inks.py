"""Encres : transmittance et passage en espace densité.

Le modèle de surimpression est multiplicatif (doc/separation.md) :

    Rendu = Papier × Π (1 − aᵢ · opacitéᵢ · (1 − Couleurᵢ))

Le facteur d'une encre à couverture pleine, `1 − o·(1 − C)`, est sa
**transmittance** : ce qu'elle laisse passer. Le logarithme la transforme en
densité, et le produit devient une somme — c'est ce qui rend la séparation
générale résoluble par moindres carrés.

Ce module ne sépare rien : il fournit les grandeurs dont `separation` a besoin.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .color import LUMA_COEFFS
from .config import Ink

#: Plancher appliqué avant le logarithme. Un noir pur donnerait une densité
#: infinie ; 1e-4 la borne à 4.0, très au-delà de ce qu'une encre riso atteint.
DENSITY_FLOOR = 1e-4


def transmittance(ink: Ink) -> np.ndarray:
    """Facteur de filtrage d'un aplat 100 %, `(3,)` en lumière linéaire.

    Une opacité < 1 rapproche le facteur de 1 : l'encre filtre moins, ce qui
    est précisément le comportement semi-transparent des encres riso.
    """
    return (1.0 - ink.opacity * (1.0 - ink.color)).astype(np.float32)


def to_density(linear: np.ndarray, floor: float = DENSITY_FLOOR) -> np.ndarray:
    """Lumière linéaire → densité."""
    return -np.log10(np.maximum(np.asarray(linear, dtype=np.float32), floor))


def from_density(density: np.ndarray) -> np.ndarray:
    """Densité → lumière linéaire."""
    return np.power(10.0, -np.asarray(density, dtype=np.float32)).astype(np.float32)


def ink_density(ink: Ink) -> np.ndarray:
    """Densité `(3,)` d'un aplat 100 % de cette encre."""
    return to_density(transmittance(ink))


def density_matrix(inks: Sequence[Ink]) -> np.ndarray:
    """Matrice `(3, N)` dont la colonne `i` est la densité de l'encre `i`.

    C'est la matrice du système que résout `density-lsq`.
    """
    return np.stack([ink_density(ink) for ink in inks], axis=1)


def luminance_density(inks: Sequence[Ink]) -> np.ndarray:
    """Densité perçue `(N,)`, un scalaire par encre.

    Sert à départager les encres quand il faut décider laquelle apporte le plus
    de noirceur par unité de couverture — la redistribution d'encrage s'appuie
    dessus.
    """
    return np.array(
        [float(to_density(np.dot(transmittance(ink), LUMA_COEFFS))) for ink in inks],
        dtype=np.float32,
    )
