import numpy as np
import pytest

from src.color import (
    ColorError,
    hex_to_linear,
    hex_to_srgb,
    linear_to_srgb,
    parse_hex,
    srgb_to_linear,
)


def test_parse_hex_normalise():
    assert parse_hex("#ff48b0") == "#FF48B0"
    assert parse_hex("ff48b0") == "#FF48B0"
    assert parse_hex("#abc") == "#AABBCC"


@pytest.mark.parametrize("bad", ["#12345", "rouge", "#GGGGGG", 42, None])
def test_parse_hex_rejette(bad):
    with pytest.raises(ColorError):
        parse_hex(bad)


def test_aller_retour_srgb_lineaire():
    values = np.linspace(0.0, 1.0, 512, dtype=np.float32)
    assert np.allclose(linear_to_srgb(srgb_to_linear(values)), values, atol=1e-6)


def test_bornes_preservees():
    assert srgb_to_linear(np.float32(0.0)) == pytest.approx(0.0)
    assert srgb_to_linear(np.float32(1.0)) == pytest.approx(1.0)


def test_courbe_srgb_pas_gamma_22():
    """La vraie courbe sRVB s'écarte d'un gamma 2.2 dans les basses lumières."""
    dark = np.float32(0.05)
    assert abs(float(srgb_to_linear(dark)) - float(dark) ** 2.2) > 1e-4


def test_hex_to_srgb_et_lineaire():
    assert np.allclose(hex_to_srgb("#FFFFFF"), [1.0, 1.0, 1.0])
    assert np.allclose(hex_to_srgb("#000000"), [0.0, 0.0, 0.0])
    assert np.allclose(hex_to_linear("#FFFFFF"), [1.0, 1.0, 1.0])


def test_couleur_lineaire_non_modifiable():
    """Une couleur de profil ne doit pas pouvoir être mutée par mégarde."""
    color = hex_to_linear("#FF48B0")
    with pytest.raises(ValueError):
        color[0] = 0.0
