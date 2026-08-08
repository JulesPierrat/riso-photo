from __future__ import annotations

import numpy as np
import pytest

from src.color import LUMA_COEFFS, hex_to_linear
from src.config import Ink
from src.inks import (
    DENSITY_FLOOR,
    density_matrix,
    from_density,
    ink_density,
    luminance_density,
    to_density,
    transmittance,
)


def ink(color: str, *, name: str = "test", opacity: float = 1.0) -> Ink:
    return Ink(
        name=name,
        label=name,
        color_hex=color,
        color=hex_to_linear(color),
        order=1,
        opacity=opacity,
        screen_angle=45.0,
        max_coverage=1.0,
    )


# --------------------------------------------------------------------------
# Densité


def test_densite_reciproque():
    values = np.linspace(0.01, 1.0, 64, dtype=np.float32)
    assert np.allclose(from_density(to_density(values)), values, atol=1e-5)


def test_densite_du_blanc_est_nulle():
    assert float(to_density(np.float32(1.0))) == pytest.approx(0.0, abs=1e-6)


def test_densite_bornee_sur_le_noir_pur():
    """Sans plancher, un noir pur donnerait une densité infinie."""
    assert np.isfinite(float(to_density(np.float32(0.0))))
    assert float(to_density(np.float32(0.0))) == pytest.approx(
        -np.log10(DENSITY_FLOOR), abs=1e-5
    )


def test_les_densites_sadditionnent():
    """C'est la propriété qui rend la séparation générale résoluble."""
    a, b = np.float32(0.5), np.float32(0.25)
    assert float(to_density(a * b)) == pytest.approx(
        float(to_density(a)) + float(to_density(b)), abs=1e-5
    )


# --------------------------------------------------------------------------
# Transmittance


def test_transmittance_dune_encre_opaque():
    """À opacité 1, l'aplat laisse passer exactement sa propre couleur."""
    pink = ink("#FF48B0")
    assert np.allclose(transmittance(pink), pink.color, atol=1e-6)


def test_lopacite_partielle_eclaircit_laplat():
    opaque = transmittance(ink("#000000", opacity=1.0))
    diffuse = transmittance(ink("#000000", opacity=0.85))
    assert float(diffuse.mean()) > float(opaque.mean())


def test_encre_totalement_transparente():
    assert np.allclose(transmittance(ink("#000000", opacity=0.0)), 1.0)


# --------------------------------------------------------------------------
# Densités d'encre


def test_le_noir_est_plus_dense_que_le_rose():
    noir = float(ink_density(ink("#231F20")).mean())
    rose = float(ink_density(ink("#FF48B0")).mean())
    assert noir > rose


def test_matrice_de_densite():
    inks = [ink("#FF48B0", name="pink"), ink("#231F20", name="black")]
    matrix = density_matrix(inks)

    assert matrix.shape == (3, 2)
    assert np.allclose(matrix[:, 0], ink_density(inks[0]))


def test_densite_par_canal_du_rose():
    """Le rose absorbe le vert et laisse passer le rouge."""
    density = ink_density(ink("#FF48B0"))
    assert float(density[0]) < float(density[1])


def test_densite_percue_ordonne_les_encres():
    inks = [ink("#FFE800", name="yellow"), ink("#0078BF", name="blue"), ink("#231F20", name="black")]
    densities = luminance_density(inks)

    assert densities[0] < densities[1] < densities[2]
    assert densities.shape == (3,)


def test_densite_percue_coherente_avec_la_luminance():
    black = ink("#231F20")
    expected = to_density(np.dot(transmittance(black), LUMA_COEFFS))
    assert float(luminance_density([black])[0]) == pytest.approx(float(expected), abs=1e-5)
