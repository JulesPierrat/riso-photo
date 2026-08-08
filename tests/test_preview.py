from __future__ import annotations

import numpy as np
import pytest

from src.color import hex_to_linear, srgb_to_linear
from src.config import build_profile
from src.image import relative_luminance
from src.inks import transmittance
from src.preview import composite
from src.separation import separate


def profile(inks, paper="#FFFFFF", **separation):
    return build_profile(
        {
            "name": "t",
            "inks": inks,
            "paper": {"color": paper},
            "separation": {"method": "luminance", **separation},
            "halftone": {"method": "none"},
        }
    )


BLACK = [{"name": "black", "color": "#000000", "opacity": 1.0}]


def test_forme_et_bornes():
    out = composite(np.zeros((1, 6, 4), dtype=np.float32), profile(BLACK))
    assert out.shape == (6, 4, 3)
    assert out.dtype == np.float32
    assert out.min() >= 0.0 and out.max() <= 1.0


def test_sans_encre_on_voit_le_papier():
    creme = profile(BLACK, paper="#F4EFE2")
    out = composite(np.zeros((1, 4, 4), dtype=np.float32), creme)
    assert np.allclose(out, hex_to_linear("#F4EFE2"), atol=1e-6)


def test_aplat_dencre_opaque_donne_sa_couleur():
    rose = profile([{"name": "pink", "color": "#FF48B0", "opacity": 1.0}])
    out = composite(np.ones((1, 4, 4), dtype=np.float32), rose)
    assert np.allclose(out, hex_to_linear("#FF48B0"), atol=1e-6)


def test_lopacite_partielle_eclaircit_laplat():
    opaque = composite(np.ones((1, 2, 2), dtype=np.float32), profile(BLACK))
    diffuse = composite(
        np.ones((1, 2, 2), dtype=np.float32),
        profile([{"name": "black", "color": "#000000", "opacity": 0.7}]),
    )
    assert float(diffuse.mean()) > float(opaque.mean())


def test_surimpression_multiplicative():
    """Deux encres superposées filtrent successivement, elles ne s'additionnent pas."""
    duo = build_profile(
        {
            "name": "duo",
            "inks": [
                {"name": "pink", "color": "#FF48B0", "order": 1, "opacity": 1.0},
                {"name": "blue", "color": "#0078BF", "order": 2, "opacity": 1.0},
            ],
            "separation": {
                "method": "duotone",
                "curves": {"pink": [[0, 0], [1, 1]], "blue": [[0, 0], [1, 1]]},
            },
        }
    )
    out = composite(np.ones((2, 2, 2), dtype=np.float32), duo)
    attendu = hex_to_linear("#FF48B0") * hex_to_linear("#0078BF")
    assert np.allclose(out, attendu, atol=1e-6)


def test_lordre_des_encres_ne_change_pas_le_rendu():
    """Le modèle est un produit : la simulation est indifférente à l'ordre.

    L'ordre de passage compte à l'impression — maculage, séchage — mais pas
    dans le calcul.
    """
    inks = [
        {"name": "pink", "color": "#FF48B0", "order": 1},
        {"name": "blue", "color": "#0078BF", "order": 2},
    ]
    curves = {"pink": [[0, 0], [1, 1]], "blue": [[0, 0], [1, 1]]}
    base = {"method": "duotone", "curves": curves}

    direct = build_profile({"name": "a", "inks": inks, "separation": base})
    inverse = build_profile(
        {
            "name": "b",
            "inks": [{**inks[1], "order": 1}, {**inks[0], "order": 2}],
            "separation": base,
        }
    )

    coverage = np.full((2, 3, 3), 0.6, dtype=np.float32)
    assert np.allclose(composite(coverage, direct), composite(coverage, inverse), atol=1e-6)


def test_aperçu_coherent_avec_les_densites():
    """La densité du rendu vaut la somme des densités déposées."""
    duo = build_profile(
        {
            "name": "duo",
            "inks": [
                {"name": "a", "color": "#808080", "order": 1, "opacity": 1.0},
                {"name": "b", "color": "#808080", "order": 2, "opacity": 1.0},
            ],
            "separation": {
                "method": "duotone",
                "total_ink_limit": 2.0,
                "curves": {"a": [[0, 0], [1, 1]], "b": [[0, 0], [1, 1]]},
            },
        }
    )
    out = composite(np.ones((2, 2, 2), dtype=np.float32), duo)
    gris = hex_to_linear("#808080")
    assert np.allclose(out, gris * gris, atol=1e-6)


# --------------------------------------------------------------------------
# Le test de bout en bout du modèle colorimétrique


def test_noir_seul_sur_blanc_reproduit_la_source_desaturee():
    """Séparation puis recomposition doivent redonner la photo, en gris.

    C'est le contrôle qui relie les deux sens du modèle : si la séparation et
    l'aperçu divergeaient, cet écart le révélerait immédiatement.
    """
    mono = profile(
        BLACK, preserve_highlights=False, total_ink_limit=1.0
    )

    x = np.linspace(0.05, 1.0, 128, dtype=np.float32)
    source = srgb_to_linear(np.repeat(x.reshape(1, 128, 1), 3, axis=2))

    coverage, _ = separate(source, mono)
    rendered = composite(coverage, mono)

    # Rendu gris : les trois canaux se confondent.
    assert float(np.abs(rendered - rendered.mean(axis=2, keepdims=True)).max()) < 5e-3

    # Et sa luminance suit celle de la source.
    ecart = np.abs(relative_luminance(rendered) - relative_luminance(source))
    assert float(ecart.max()) < 0.01


def test_encre_trop_claire_pour_les_ombres():
    """Un jaune ne peut pas faire de noir : l'aperçu doit le montrer."""
    jaune = profile([{"name": "yellow", "color": "#FFE800"}], total_ink_limit=1.0)
    source = np.zeros((1, 4, 3), dtype=np.float32)

    coverage, _ = separate(source, jaune)
    rendered = composite(coverage, jaune)

    assert float(coverage.max()) == pytest.approx(1.0, abs=1e-3)  # encre à fond
    assert float(relative_luminance(rendered).min()) > 0.3  # et pourtant clair


def test_transmittance_coherente_avec_lapercu():
    """`composite` doit utiliser exactement la transmittance de `inks`."""
    mono = profile([{"name": "pink", "color": "#FF48B0", "opacity": 0.85}])
    out = composite(np.ones((1, 2, 2), dtype=np.float32), mono)
    assert np.allclose(out, transmittance(mono.inks[0]), atol=1e-6)


def test_le_profil_mono_noir_atteint_vraiment_le_noir():
    """Garde-fou sur le plafond d'encrage du profil livré.

    Repasser `max_coverage` sous 1.0 ferait plafonner les ombres en gris moyen
    — 10 % de papier nu suffisent à éclaircir tout le bas de la gamme.
    """
    from src.config import load_profile

    mono = load_profile("mono-noir")
    x = np.linspace(0.0, 1.0, 128, dtype=np.float32)
    source = srgb_to_linear(np.repeat(x.reshape(1, 128, 1), 3, axis=2))

    coverage, _ = separate(source, mono)
    rendered = composite(coverage, mono)

    # Le noir de l'encre elle-même, pas un gris.
    assert float(relative_luminance(rendered).min()) < 0.02
