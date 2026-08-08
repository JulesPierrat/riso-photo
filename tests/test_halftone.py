from __future__ import annotations

import numpy as np
import pytest

from src.config import HalftoneCfg
from src.errors import RisoError
from src.halftone import (
    bayer,
    bayer_matrix,
    blue_noise,
    blue_noise_matrix,
    clustered_dot,
    halftone,
)


def cfg(**kwargs) -> HalftoneCfg:
    base = dict(method="clustered-dot", lpi=60, dot_shape="round", matrix_size=8)
    return HalftoneCfg(**{**base, **kwargs})


def uniform(value: float, size: int = 512) -> np.ndarray:
    return np.full((size, size), value, dtype=np.float32)


TONES = [0.05, 0.1, 0.25, 0.5, 0.75, 0.9]


# --------------------------------------------------------------------------
# Sortie binaire


@pytest.mark.parametrize(
    "screen",
    [
        lambda c: clustered_dot(c, 60, 600, 15.0),
        lambda c: bayer(c, 8),
        blue_noise,
    ],
)
def test_sortie_strictement_binaire(screen):
    """Une risographe ne sait déposer que de l'encre ou rien."""
    rng = np.random.default_rng(0)
    out = screen(rng.random((200, 200), dtype=np.float32))
    assert set(np.unique(out)) <= {0.0, 1.0}


@pytest.mark.parametrize(
    "screen",
    [
        lambda c: clustered_dot(c, 60, 600, 15.0),
        lambda c: bayer(c, 8),
        blue_noise,
    ],
)
def test_extremes_intacts(screen):
    assert float(screen(uniform(0.0, 128)).max()) == 0.0
    assert float(screen(uniform(1.0, 128)).min()) == 1.0


# --------------------------------------------------------------------------
# Conservation de la densité — le critère de fin du lot


@pytest.mark.parametrize("tone", TONES)
@pytest.mark.parametrize("shape", ["round", "ellipse", "square", "line"])
def test_am_conserve_la_densite(tone, shape):
    """Un aplat tramé puis moyenné doit redonner la couverture demandée.

    Sans égalisation de la fonction de point, la trame décalerait toute la
    gamme tonale — un défaut discret mais systématique.
    """
    out = clustered_dot(uniform(tone, 600), 60, 600, 15.0, shape)
    assert float(out.mean()) == pytest.approx(tone, abs=0.02)


@pytest.mark.parametrize("tone", TONES)
def test_bruit_bleu_conserve_la_densite(tone):
    assert float(blue_noise(uniform(tone)).mean()) == pytest.approx(tone, abs=0.02)


@pytest.mark.parametrize("tone", TONES)
def test_bayer_conserve_la_densite(tone):
    assert float(bayer(uniform(tone), 8).mean()) == pytest.approx(tone, abs=0.02)


@pytest.mark.parametrize("angle", [0.0, 15.0, 45.0, 75.0])
def test_am_conserve_la_densite_a_tout_angle(angle):
    out = clustered_dot(uniform(0.35, 600), 60, 600, angle)
    assert float(out.mean()) == pytest.approx(0.35, abs=0.02)


def test_am_conserve_la_densite_sur_un_degrade():
    rampe = np.tile(np.linspace(0, 1, 600, dtype=np.float32), (600, 1))
    assert float(clustered_dot(rampe, 60, 600, 45.0).mean()) == pytest.approx(0.5, abs=0.02)


# --------------------------------------------------------------------------
# Trame AM : géométrie


def test_les_points_grossissent_depuis_le_centre():
    """À faible couverture, l'encre forme des îlots isolés, pas un voile."""
    clair = clustered_dot(uniform(0.1, 600), 60, 600, 0.0)
    fonce = clustered_dot(uniform(0.4, 600), 60, 600, 0.0)

    # Le motif clair est inclus dans le motif foncé : les points grossissent.
    assert np.all(fonce[clair > 0] > 0)


def test_la_lineature_pilote_la_taille_des_points():
    grosse = clustered_dot(uniform(0.5, 600), 30, 600, 0.0)
    fine = clustered_dot(uniform(0.5, 600), 90, 600, 0.0)

    # Moins de linéature = points plus gros = moins de transitions.
    assert int(np.abs(np.diff(grosse, axis=1)).sum()) < int(
        np.abs(np.diff(fine, axis=1)).sum()
    )


def test_langle_change_lorientation():
    a = clustered_dot(uniform(0.3, 400), 50, 600, 0.0)
    b = clustered_dot(uniform(0.3, 400), 50, 600, 45.0)
    assert not np.array_equal(a, b)


def test_lineature_trop_fine_pour_la_resolution():
    with pytest.raises(RisoError, match="linéature trop fine"):
        clustered_dot(uniform(0.5, 64), 600, 300, 0.0)


def test_deux_angles_ecartes_ne_moirent_pas():
    """15° et 45° : la superposition ne doit pas faire apparaître de motif.

    Un moiré se manifeste par des variations de densité à grande échelle. On
    compare l'écart-type des moyennes par blocs à celui d'une paire d'angles
    volontairement trop proches.
    """
    def modulation(angle_a, angle_b):
        a = clustered_dot(uniform(0.5, 480), 40, 480, angle_a)
        b = clustered_dot(uniform(0.5, 480), 40, 480, angle_b)
        ensemble = np.maximum(a, b)
        blocs = ensemble.reshape(12, 40, 12, 40).mean(axis=(1, 3))
        return float(blocs.std())

    assert modulation(15.0, 45.0) < modulation(15.0, 17.0)


# --------------------------------------------------------------------------
# Masques ordonnés


def test_matrice_de_bayer():
    matrix = bayer_matrix(4)
    assert matrix.shape == (4, 4)
    assert sorted(matrix.ravel()) == list(range(16))


def test_masque_bleu_est_une_permutation_complete():
    ranks = blue_noise_matrix()
    assert sorted(ranks.ravel()) == list(range(ranks.size))


def test_le_masque_bleu_repartit_mieux_que_bayer():
    """Le bruit bleu doit être stochastique, pas périodique.

    Un motif régulier concentre son énergie sur quelques fréquences ; le bruit
    bleu l'étale. On le mesure par le pic du spectre d'un aplat tramé.
    """
    def pic(motif):
        spectre = np.abs(np.fft.fft2(motif - motif.mean()))
        return float(spectre.max() / spectre.mean())

    aplat = uniform(0.25, 256)
    assert pic(blue_noise(aplat)) < pic(bayer(aplat, 8))


def test_le_masque_bleu_evite_les_basses_frequences():
    """Bruit « bleu » : peu d'énergie à basse fréquence, donc pas de paquets."""
    motif = blue_noise(uniform(0.5, 256)) - 0.5
    spectre = np.abs(np.fft.fftshift(np.fft.fft2(motif)))

    centre = spectre[112:144, 112:144].mean()  # basses fréquences
    assert centre < spectre.mean()


# --------------------------------------------------------------------------
# Répartiteur


def test_none_laisse_passer_le_ton_continu():
    coverage = uniform(0.37, 32)
    assert halftone(coverage, cfg(method="none"), 45.0, 600) is coverage


@pytest.mark.parametrize("method", ["clustered-dot", "bayer", "blue-noise"])
def test_toutes_les_methodes_tramen(method):
    out = halftone(uniform(0.5, 128), cfg(method=method), 45.0, 600)
    assert set(np.unique(out)) <= {0.0, 1.0}
    assert float(out.mean()) == pytest.approx(0.5, abs=0.02)


def test_les_dimensions_sont_preservees():
    out = halftone(np.full((97, 53), 0.4, dtype=np.float32), cfg(), 15.0, 600)
    assert out.shape == (97, 53)
    assert out.dtype == np.float32


def test_trame_alignee_sur_la_grille_pixel():
    """Cas dégénéré : à 0° avec une cellule entière, toutes les cellules
    échantillonnent les mêmes points et la gamme se décalait de 4 %."""
    for tone in TONES:
        out = clustered_dot(uniform(tone, 600), 60, 600, 0.0)
        assert float(out.mean()) == pytest.approx(tone, abs=0.01)


def test_la_correction_ne_touche_pas_les_angles_obliques():
    from src.halftone import _deariased_cell

    assert _deariased_cell(10.0, 0.0) != 10.0  # aligné + cellule entière
    assert _deariased_cell(10.0, 45.0) == 10.0  # oblique
    assert _deariased_cell(10.53, 0.0) == 10.53  # cellule non entière
