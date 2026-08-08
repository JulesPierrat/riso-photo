"""Séparation : d'une image RVB vers N cartes de couverture d'encre.

Une carte de couverture vaut `1.0` là où l'encre est pleine, `0.0` là où le
papier reste nu — toujours dans ce sens, quelle que soit la convention de
sortie du profil. Voir doc/separation.md pour le modèle et les méthodes.
"""

from __future__ import annotations

import numpy as np

from .color import LUMA_COEFFS
from .config import Profile
from .errors import NotImplementedYet
from .image import luminance, relative_luminance
from .inks import luminance_density, transmittance

#: Couverture en deçà de laquelle `preserve_highlights` remet à zéro. Sous 2 %,
#: une trame ne dépose qu'un point isolé par cellule : il salit les blancs sans
#: apporter de nuance.
HIGHLIGHT_FLOOR = 0.02

#: Finesse des tables de courbes de réponse. Une courbe est linéaire par
#: morceaux : 8192 échantillons la restituent à mieux qu'un niveau 8 bits pour
#: toute pente raisonnable.
_CURVE_LUT_SIZE = 8192

_IMPLEMENTED = ("luminance", "duotone", "tritone")


def apply_curve(x: np.ndarray, points) -> np.ndarray:
    """Courbe de réponse linéaire par morceaux, définie par ses points.

    Passe par une table plutôt que par `np.interp` direct : sur les dizaines de
    millions de pixels d'un A4 à 600 dpi, `np.interp` produirait un
    intermédiaire float64 de plusieurs centaines de mégaoctets.
    """
    xs = np.array([p[0] for p in points], dtype=np.float64)
    ys = np.array([p[1] for p in points], dtype=np.float64)

    lut = np.interp(
        np.linspace(0.0, 1.0, _CURVE_LUT_SIZE), xs, ys
    ).astype(np.float32)

    index = np.rint(np.clip(x, 0.0, 1.0) * (_CURVE_LUT_SIZE - 1)).astype(np.int32)
    return lut[index]


# --------------------------------------------------------------------------
# Méthodes


def _separate_luminance(img: np.ndarray, profile: Profile) -> np.ndarray:
    """Une seule encre : inversion directe du modèle de surimpression.

    Le rendu d'une couverture `a` vaut `Papier × (1 − a·(1 − T))`, où `T` est la
    transmittance de l'aplat. On résout en luminance :

        a = (1 − Y_cible / Y_papier) / (1 − T_Y)

    On n'utilise donc pas `1 − luminance perceptuelle` : ce serait cohérent à
    l'œil mais pas avec le modèle, et l'aperçu ne correspondrait plus au calque.
    """
    ink = profile.inks[0]
    paper_y = float(np.dot(profile.paper.color, LUMA_COEFFS))
    trans_y = float(np.dot(transmittance(ink), LUMA_COEFFS))

    reach = 1.0 - trans_y
    if reach < 1e-4 or paper_y < 1e-4:
        # Encre indiscernable du papier : aucune couverture ne rapproche du
        # but. La validation du profil l'a déjà signalé.
        return np.zeros((1, *img.shape[:2]), dtype=np.float32)

    target = relative_luminance(img)
    coverage = (1.0 - target / paper_y) / reach
    return np.clip(coverage, 0.0, 1.0)[np.newaxis].astype(np.float32)


def _separate_tonal(img: np.ndarray, profile: Profile) -> np.ndarray:
    """`duotone` / `tritone` : une courbe de réponse par encre.

    Méthode volontairement aveugle à la chromie de la photo — c'est un parti
    pris graphique, pas une reproduction. Les courbes prennent en entrée la
    luminance perceptuelle, où le gris moyen vaut ~0.5 : c'est ce qui rend les
    points de contrôle du profil lisibles.
    """
    curves = profile.separation.curves or {}
    lum = luminance(img)
    return np.stack([apply_curve(lum, curves[ink.name]) for ink in profile.inks])


# --------------------------------------------------------------------------
# Limitation d'encrage


def limit_ink(coverage: np.ndarray, profile: Profile) -> tuple[np.ndarray, dict]:
    """Applique les plafonds par encre puis l'encrage total.

    Le plafond total n'est pas un simple écrêtage : couper brutalement
    aplatirait les ombres et y produirait des cassures visibles. On réduit les
    encres claires et on compense par l'encre la plus foncée, qui apporte plus
    de densité par unité de couverture — la noirceur perçue est à peu près
    conservée alors que l'encrage total redescend.
    """
    inks = profile.inks
    caps = np.array([ink.max_coverage for ink in inks], dtype=np.float32)
    coverage = np.minimum(coverage, caps[:, np.newaxis, np.newaxis])

    limit = float(profile.separation.total_ink_limit)
    total = coverage.sum(axis=0)
    over = total > limit
    limited_fraction = float(np.count_nonzero(over)) / total.size

    if over.any() and len(inks) > 1:
        coverage = _redistribute(coverage, profile, caps, limit, over)

    # Filet de sécurité : la redistribution est bornée de plusieurs côtés
    # (plafond de l'encre foncée, couverture disponible sur les claires) et
    # peut ne pas suffire. L'invariant, lui, ne se négocie pas.
    total = coverage.sum(axis=0)
    excess = total > limit
    if excess.any():
        scale = np.where(excess, limit / np.maximum(total, 1e-6), 1.0)
        coverage = coverage * scale

    total = coverage.sum(axis=0)
    return coverage.astype(np.float32), {
        "total_ink_max": float(total.max()),
        "total_ink_mean": float(total.mean()),
        "limited_fraction": limited_fraction,
    }


def _redistribute(
    coverage: np.ndarray,
    profile: Profile,
    caps: np.ndarray,
    limit: float,
    over: np.ndarray,
) -> np.ndarray:
    """Reporte l'excédent des encres claires vers l'encre la plus foncée.

    On cherche le facteur `f` par lequel réduire les claires tel qu'après
    compensation, le total retombe exactement sur la limite. En notant `D` les
    densités perçues, `S` la somme des claires et `c = Σ aⱼ·Dⱼ / D_foncée` la
    couverture équivalente en encre foncée :

        f·S + a_foncée + (1 − f)·c = limite   ⟹   f = (limite − a_foncée − c) / (S − c)
    """
    densities = luminance_density(profile.inks)
    dark = int(np.argmax(densities))
    light = [i for i in range(len(profile.inks)) if i != dark]

    dark_cov = coverage[dark]
    light_cov = coverage[light]
    light_density = densities[light][:, np.newaxis, np.newaxis]

    total_light = light_cov.sum(axis=0)
    equivalent = (light_cov * light_density).sum(axis=0) / densities[dark]

    denominator = total_light - equivalent
    factor = np.where(
        denominator > 1e-6,
        (limit - dark_cov - equivalent) / np.maximum(denominator, 1e-6),
        # Encres de densités trop proches : rien à gagner à transférer, on
        # laisse le filet de sécurité faire une réduction uniforme.
        1.0,
    )
    factor = np.where(over, np.clip(factor, 0.0, 1.0), 1.0)

    out = coverage.copy()
    out[light] = light_cov * factor
    out[dark] = np.minimum(dark_cov + (1.0 - factor) * equivalent, caps[dark])
    return out


# --------------------------------------------------------------------------
# Point d'entrée


def separate(img: np.ndarray, profile: Profile) -> tuple[np.ndarray, dict]:
    """Sépare une image RVB linéaire en `(N, H, W)` cartes de couverture.

    Rend aussi les statistiques d'encrage, destinées au `todo.md` : elles ne
    sont connues qu'ici et seraient impossibles à recalculer ensuite.
    """
    method = profile.separation.method
    if method not in _IMPLEMENTED:
        raise NotImplementedYet(
            f"La séparation {method!r} n'est pas encore écrite (lot 6 pour "
            "`density-lsq`, lot 8 pour `cmyk` — voir doc/plan.md).\n"
            f"Méthodes disponibles : {', '.join(_IMPLEMENTED)}."
        )

    if method == "luminance":
        coverage = _separate_luminance(img, profile)
    else:
        coverage = _separate_tonal(img, profile)

    if profile.separation.preserve_highlights:
        coverage = np.where(coverage < HIGHLIGHT_FLOOR, 0.0, coverage)

    return limit_ink(coverage, profile)
