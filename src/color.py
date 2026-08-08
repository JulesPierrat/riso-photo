"""Conversions colorimétriques de base.

Module volontairement sans dépendance vers le reste de `src/` : il est utilisé
aussi bien par `config` (parsing des couleurs d'encre) que par `image` et
`inks`, et le sortir évite un cycle d'imports entre eux.

Toute la chaîne de traitement travaille en **espace linéaire**. Les conversions
ci-dessous utilisent la vraie courbe sRVB — segment linéaire sous le seuil puis
puissance 2.4 — et non un gamma 2.2 approché : l'écart se voit dans les basses
lumières, exactement là où la risographe est déjà fragile.
"""

from __future__ import annotations

import re

import numpy as np

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")

_SRGB_THRESHOLD = 0.04045
_LINEAR_THRESHOLD = 0.0031308


class ColorError(ValueError):
    """Couleur mal formée."""


def parse_hex(value: str) -> str:
    """Normalise une couleur hexadécimale en `#RRGGBB` majuscule.

    Accepte les formes courtes (`#abc`), avec ou sans dièse.
    """
    if not isinstance(value, str):
        raise ColorError(f"couleur hexadécimale attendue, reçu {value!r}")
    match = _HEX_RE.match(value.strip())
    if match is None:
        raise ColorError(f"couleur hexadécimale mal formée : {value!r}")
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return "#" + digits.upper()


def hex_to_srgb(value: str) -> np.ndarray:
    """`#RRGGBB` → tableau (3,) sRVB encodé, dans [0, 1]."""
    digits = parse_hex(value)[1:]
    return np.array(
        [int(digits[i : i + 2], 16) / 255.0 for i in (0, 2, 4)], dtype=np.float32
    )


def srgb_to_linear(a: np.ndarray) -> np.ndarray:
    """sRVB encodé → linéaire."""
    a = np.asarray(a, dtype=np.float32)
    return np.where(
        a <= _SRGB_THRESHOLD,
        a / 12.92,
        np.power((a + 0.055) / 1.055, 2.4),
    ).astype(np.float32)


def linear_to_srgb(a: np.ndarray) -> np.ndarray:
    """Linéaire → sRVB encodé."""
    a = np.asarray(a, dtype=np.float32)
    return np.where(
        a <= _LINEAR_THRESHOLD,
        a * 12.92,
        1.055 * np.power(np.maximum(a, 0.0), 1.0 / 2.4) - 0.055,
    ).astype(np.float32)


def hex_to_linear(value: str) -> np.ndarray:
    """`#RRGGBB` → tableau (3,) sRVB linéaire, en lecture seule."""
    out = srgb_to_linear(hex_to_srgb(value))
    out.setflags(write=False)
    return out
