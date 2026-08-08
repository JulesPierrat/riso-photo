from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from src.color import linear_to_srgb, srgb_to_linear
from src.config import ToneCfg
from src.errors import RisoError
from src.image import (
    apply_tone,
    load_linear,
    luminance,
    relative_luminance,
    resize_to,
    resolution_warning,
    source_size,
    target_long_edge_px,
    tone_curve,
)


def tone(**kwargs) -> ToneCfg:
    base = dict(gamma=1.0, contrast=0.0, black_point=0.0, white_point=1.0, desaturate=0.0)
    return ToneCfg(**{**base, **kwargs})


def encoded(*channels: float) -> np.ndarray:
    """Un pixel `(1, 1, 3)` linéaire, décrit par ses valeurs sRVB encodées."""
    return srgb_to_linear(np.array([[list(channels)]], dtype=np.float32))


# --------------------------------------------------------------------------
# Chargement


def test_chargement_forme_et_domaine(tmp_path, make_image):
    path = tmp_path / "mire.png"
    make_image(64, 48).save(path)

    img = load_linear(path)

    assert img.shape == (48, 64, 3)
    assert img.dtype == np.float32
    assert img.min() >= 0.0 and img.max() <= 1.0


def test_chargement_lineaire_pas_encode(tmp_path):
    """Un gris moyen sRVB doit ressortir à ~0.216, pas à ~0.5."""
    path = tmp_path / "gris.png"
    Image.new("RGB", (4, 4), (128, 128, 128)).save(path)

    assert float(load_linear(path).mean()) == pytest.approx(0.2158, abs=1e-3)


def test_niveaux_de_gris_converti_en_rvb(tmp_path):
    path = tmp_path / "gris.png"
    Image.new("L", (8, 8), 200).save(path)

    img = load_linear(path)
    assert img.shape == (8, 8, 3)
    assert np.allclose(img[:, :, 0], img[:, :, 2])


def test_transparence_aplatie_sur_du_blanc(tmp_path):
    """Une zone transparente correspond au papier nu, donc à du blanc."""
    path = tmp_path / "trou.png"
    Image.new("RGBA", (4, 4), (255, 0, 0, 0)).save(path)

    assert np.allclose(load_linear(path), 1.0)


def test_orientation_exif_appliquee(tmp_path, make_image):
    path = tmp_path / "portrait.jpg"
    img = make_image(60, 40)
    exif = img.getexif()
    exif[274] = 6  # rotation 90°, échange les dimensions
    img.save(path, exif=exif)

    assert source_size(path) == (40, 60)
    assert load_linear(path).shape[:2] == (60, 40)


def test_dimensions_sans_decodage(tmp_path, make_image):
    path = tmp_path / "mire.jpg"
    make_image(120, 80).save(path)
    assert source_size(path) == (120, 80)


def test_image_illisible(tmp_path):
    path = tmp_path / "casse.jpg"
    path.write_bytes(b"pas une image")
    with pytest.raises(RisoError):
        load_linear(path)


# --------------------------------------------------------------------------
# Géométrie


def test_taille_cible_en_pixels():
    assert target_long_edge_px(297, 300) == 3508  # A4 @ 300 dpi
    assert target_long_edge_px(297, 600) == 7016
    assert target_long_edge_px(25.4, 300) == 300  # un pouce


def test_redimensionnement_preserve_le_ratio():
    img = np.zeros((300, 400, 3), dtype=np.float32)
    out = resize_to(img, 800)
    assert out.shape == (600, 800, 3)


def test_redimensionnement_portrait():
    img = np.zeros((400, 300, 3), dtype=np.float32)
    assert resize_to(img, 800).shape == (800, 600, 3)


def test_redimensionnement_sans_effet_si_deja_a_la_taille():
    img = np.zeros((300, 400, 3), dtype=np.float32)
    assert resize_to(img, 400) is img


def test_redimensionnement_reste_dans_les_bornes():
    """Lanczos dépasse sur les contrastes francs : la sortie doit être écrêtée."""
    img = np.zeros((64, 64, 3), dtype=np.float32)
    img[:, 32:] = 1.0

    out = resize_to(img, 200)
    assert out.min() >= 0.0 and out.max() <= 1.0
    assert out.dtype == np.float32


def test_redimensionnement_preserve_la_moyenne():
    rng = np.random.default_rng(0)
    img = rng.random((200, 200, 3), dtype=np.float32) * 0.6 + 0.2
    assert float(resize_to(img, 100).mean()) == pytest.approx(float(img.mean()), abs=0.01)


def test_avertissement_de_sous_resolution():
    assert resolution_warning(4000, 3508) is None
    assert resolution_warning(3508, 3508) is None

    message = resolution_warning(1000, 3508)
    assert message is not None
    assert "3.5×" in message


# --------------------------------------------------------------------------
# Luminance


def test_luminance_des_extremes():
    blanc = np.ones((2, 2, 3), dtype=np.float32)
    noir = np.zeros((2, 2, 3), dtype=np.float32)

    assert float(luminance(blanc).mean()) == pytest.approx(1.0, abs=1e-5)
    assert float(luminance(noir).mean()) == pytest.approx(0.0, abs=1e-5)


def test_luminance_perceptuelle_du_gris_moyen():
    """Un gris moyen doit valoir ~0.5 sur l'échelle que prennent les courbes."""
    gris = encoded(0.5, 0.5, 0.5)
    assert float(luminance(gris)) == pytest.approx(0.5, abs=1e-3)
    assert float(relative_luminance(gris)) == pytest.approx(0.214, abs=1e-3)


def test_le_vert_pese_plus_que_le_bleu():
    vert = np.array([[[0.0, 1.0, 0.0]]], dtype=np.float32)
    bleu = np.array([[[0.0, 0.0, 1.0]]], dtype=np.float32)
    assert float(relative_luminance(vert)) > float(relative_luminance(bleu))


def test_forme_de_la_luminance():
    assert luminance(np.zeros((7, 5, 3), dtype=np.float32)).shape == (7, 5)


# --------------------------------------------------------------------------
# Corrections tonales


def test_tone_par_defaut_est_lidentite():
    """Un profil sans section `tone` ne doit strictement rien changer."""
    rng = np.random.default_rng(0)
    img = rng.random((16, 16, 3), dtype=np.float32)
    assert apply_tone(img, tone()) is img


def test_gamma_superieur_a_1_eclaircit():
    gris = encoded(0.5, 0.5, 0.5)
    assert float(apply_tone(gris, tone(gamma=1.5)).mean()) > float(gris.mean())


def test_gamma_inferieur_a_1_assombrit():
    gris = encoded(0.5, 0.5, 0.5)
    assert float(apply_tone(gris, tone(gamma=0.7)).mean()) < float(gris.mean())


def test_gamma_preserve_les_extremes():
    extremes = encoded(0.0, 1.0, 0.0)
    out = linear_to_srgb(apply_tone(extremes, tone(gamma=1.4)))
    assert float(out[0, 0, 0]) == pytest.approx(0.0, abs=1e-4)
    assert float(out[0, 0, 1]) == pytest.approx(1.0, abs=1e-4)


def test_niveaux_recadrent_lhistogramme():
    img = encoded(0.1, 0.5, 0.9)
    out = linear_to_srgb(apply_tone(img, tone(black_point=0.1, white_point=0.9)))

    assert float(out[0, 0, 0]) == pytest.approx(0.0, abs=1e-3)
    assert float(out[0, 0, 2]) == pytest.approx(1.0, abs=1e-3)
    assert float(out[0, 0, 1]) == pytest.approx(0.5, abs=1e-3)


def test_contraste_positif_ecarte_les_tons():
    sombre = encoded(0.25, 0.25, 0.25)
    clair = encoded(0.75, 0.75, 0.75)
    cfg = tone(contrast=0.6)

    assert float(linear_to_srgb(apply_tone(sombre, cfg))[0, 0, 0]) < 0.25
    assert float(linear_to_srgb(apply_tone(clair, cfg))[0, 0, 0]) > 0.75


def test_contraste_negatif_resserre_les_tons():
    sombre = encoded(0.25, 0.25, 0.25)
    cfg = tone(contrast=-0.6)
    assert float(linear_to_srgb(apply_tone(sombre, cfg))[0, 0, 0]) > 0.25


def test_contraste_fixe_le_gris_moyen_et_les_extremes():
    img = encoded(0.0, 0.5, 1.0)
    out = linear_to_srgb(apply_tone(img, tone(contrast=0.9)))
    assert np.allclose(out[0, 0], [0.0, 0.5, 1.0], atol=2e-3)


@pytest.mark.parametrize("amount", [-1.0, -0.5, 0.5, 1.0])
def test_contraste_reste_monotone(amount):
    """Une courbe non monotone inverserait des tons : postérisation garantie."""
    ramp = srgb_to_linear(np.linspace(0, 1, 256, dtype=np.float32).reshape(1, 256, 1))
    out = apply_tone(np.repeat(ramp, 3, axis=2), tone(contrast=amount))
    assert np.all(np.diff(out[0, :, 0]) >= -1e-6)


def test_desaturation_complete():
    couleur = encoded(0.9, 0.3, 0.1)
    out = apply_tone(couleur, tone(desaturate=1.0))
    assert float(out[0, 0, 0]) == pytest.approx(float(out[0, 0, 1]), abs=1e-5)
    assert float(out[0, 0, 1]) == pytest.approx(float(out[0, 0, 2]), abs=1e-5)


def test_desaturation_partielle():
    couleur = encoded(0.9, 0.3, 0.1)
    ecart = lambda a: float(a.max() - a.min())  # noqa: E731
    assert ecart(apply_tone(couleur, tone(desaturate=0.5))) < ecart(couleur)


def test_sortie_toujours_dans_les_bornes():
    rng = np.random.default_rng(1)
    img = rng.random((32, 32, 3), dtype=np.float32)
    cfg = tone(gamma=0.5, contrast=1.0, black_point=0.3, white_point=0.7, desaturate=0.4)

    out = apply_tone(img, cfg)
    assert out.min() >= 0.0 and out.max() <= 1.0
    assert out.dtype == np.float32


def test_la_table_colle_a_la_courbe_de_reference():
    """`apply_tone` passe par une table : elle doit rester fidèle au calcul exact."""
    cfg = tone(gamma=1.3, contrast=0.5, black_point=0.05, white_point=0.95)
    ramp = np.linspace(0.0, 1.0, 4096, dtype=np.float32).reshape(1, 4096, 1)

    approx = apply_tone(np.repeat(ramp, 3, axis=2), cfg)[0, :, 0]
    exact = tone_curve(ramp[0, :, 0], cfg)

    # Moins d'un demi-niveau 8 bits d'écart, mesuré en domaine perceptuel.
    ecart = np.abs(linear_to_srgb(approx) - linear_to_srgb(exact)).max()
    assert float(ecart) < 1.0 / 512


def test_la_table_preserve_les_extremes():
    cfg = tone(gamma=1.3, contrast=0.5)
    extremes = np.array([[[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]], dtype=np.float32)

    out = apply_tone(extremes, cfg)
    assert float(out[0, 0, 0]) == pytest.approx(0.0, abs=1e-6)
    assert float(out[0, 1, 0]) == pytest.approx(1.0, abs=1e-6)
