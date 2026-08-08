from __future__ import annotations

import struct

import numpy as np
import pytest
from PIL import Image

from src.config import Ink, OutputCfg
from src.color import hex_to_linear
from src.output import add_margin_and_marks, layer_filename, write_layer, write_preview


def cfg(**kwargs) -> OutputCfg:
    base = dict(
        dpi=300,
        format="png",
        bit_depth=8,
        invert=False,
        long_edge_mm=297.0,
        registration_marks=False,
        margin_mm=0.0,
    )
    return OutputCfg(**{**base, **kwargs})


def ink(name: str, order: int = 1) -> Ink:
    return Ink(
        name=name,
        label=name,
        color_hex="#000000",
        color=hex_to_linear("#000000"),
        order=order,
        opacity=1.0,
        screen_angle=45.0,
        max_coverage=1.0,
    )


# --------------------------------------------------------------------------
# Nommage


def test_nommage_avec_ordre_de_passage():
    assert layer_filename(ink("fluo-pink", 1), cfg()) == "01_fluo-pink.png"
    assert layer_filename(ink("black", 2), cfg(format="tiff")) == "02_black.tiff"


def test_le_prefixe_ordonne_les_fichiers():
    noms = sorted(layer_filename(ink(f"encre-{i}", i), cfg()) for i in (3, 1, 2))
    assert [n[:2] for n in noms] == ["01", "02", "03"]


# --------------------------------------------------------------------------
# Convention de valeur


def test_noir_vaut_encre_pleine(tmp_path):
    path = tmp_path / "calque.png"
    coverage = np.array([[0.0, 1.0]], dtype=np.float32)

    write_layer(coverage, path, cfg())

    assert np.array_equal(np.asarray(Image.open(path)), [[255, 0]])


def test_invert_produit_un_positif(tmp_path):
    path = tmp_path / "calque.png"
    coverage = np.array([[0.0, 1.0]], dtype=np.float32)

    write_layer(coverage, path, cfg(invert=True))

    assert np.array_equal(np.asarray(Image.open(path)), [[0, 255]])


def test_calque_en_niveaux_de_gris(tmp_path):
    """Un calque n'a pas de couleur : la couleur est l'encre en machine."""
    path = tmp_path / "calque.png"
    write_layer(np.zeros((4, 4), dtype=np.float32), path, cfg())

    with Image.open(path) as img:
        assert img.mode == "L"


def test_demi_couverture(tmp_path):
    path = tmp_path / "calque.png"
    write_layer(np.array([[0.5]], dtype=np.float32), path, cfg())
    assert int(np.asarray(Image.open(path))[0, 0]) == 128


# --------------------------------------------------------------------------
# Formats


def png_bit_depth(path) -> int:
    """Profondeur déclarée dans l'en-tête IHDR.

    PIL relit un PNG 16 bits en mode `I` sur 32 bits : c'est le fichier sur
    disque qui compte, pas ce que la bibliothèque en fait ensuite.
    """
    return struct.unpack(">IIBB", path.read_bytes()[16:26])[2]


def test_seize_bits(tmp_path):
    path = tmp_path / "calque.png"
    coverage = np.array([[0.0, 0.5, 1.0]], dtype=np.float32)

    write_layer(coverage, path, cfg(bit_depth=16))

    assert png_bit_depth(path) == 16
    assert list(np.asarray(Image.open(path))[0]) == [65535, 32768, 0]


def test_huit_bits_par_defaut(tmp_path):
    path = tmp_path / "calque.png"
    write_layer(np.zeros((2, 2), dtype=np.float32), path, cfg())
    assert png_bit_depth(path) == 8


def test_tiff(tmp_path):
    path = tmp_path / "calque.tiff"
    write_layer(np.zeros((4, 4), dtype=np.float32), path, cfg(format="tiff"))

    with Image.open(path) as img:
        assert img.format == "TIFF"


def test_resolution_inscrite_dans_le_fichier(tmp_path):
    """L'imprimeur doit retrouver le dpi sans avoir à le demander."""
    path = tmp_path / "calque.png"
    write_layer(np.zeros((4, 4), dtype=np.float32), path, cfg(dpi=600))

    with Image.open(path) as img:
        assert [round(v) for v in img.info["dpi"]] == [600, 600]


def test_ecriture_impossible(tmp_path):
    from src.errors import RisoError

    with pytest.raises(RisoError, match="écriture impossible"):
        write_layer(np.zeros((2, 2), dtype=np.float32), tmp_path / "absent" / "x.png", cfg())


# --------------------------------------------------------------------------
# Aperçu


def test_apercu_en_rvb_huit_bits(tmp_path):
    path = tmp_path / "preview.png"
    write_preview(np.zeros((4, 6, 3), dtype=np.float32), path, cfg(bit_depth=16))

    with Image.open(path) as img:
        assert img.mode == "RGB"
        assert img.size == (6, 4)


def test_apercu_encode_en_srvb(tmp_path):
    """L'aperçu est fait pour être regardé : il ressort en sRVB, pas en linéaire."""
    path = tmp_path / "preview.png"
    gris = np.full((2, 2, 3), 0.2158, dtype=np.float32)  # gris moyen, linéaire

    write_preview(gris, path, cfg())

    assert int(np.asarray(Image.open(path))[0, 0, 0]) == pytest.approx(128, abs=1)


def test_apercu_bornes(tmp_path):
    path = tmp_path / "preview.png"
    write_preview(np.array([[[0.0, 1.0, 0.5]]], dtype=np.float32), path, cfg())

    pixel = np.asarray(Image.open(path))[0, 0]
    assert pixel[0] == 0 and pixel[1] == 255


# --------------------------------------------------------------------------
# Marges et repères de calage


def marges(**kwargs):
    base = dict(margin_mm=5.0, dpi=600, registration_marks=True)
    return cfg(**{**base, **kwargs})


def test_la_marge_agrandit_le_calque():
    layer = np.zeros((100, 200), dtype=np.float32)
    out = add_margin_and_marks(layer, marges(registration_marks=False))

    marge = round(5.0 / 25.4 * 600)  # 118 px
    assert out.shape == (100 + 2 * marge, 200 + 2 * marge)


def test_la_marge_est_du_papier_nu():
    layer = np.ones((40, 40), dtype=np.float32)
    out = add_margin_and_marks(layer, marges(registration_marks=False))

    assert float(out[0, :].max()) == 0.0
    assert float(out[:, 0].max()) == 0.0
    assert float(out[118:158, 118:158].min()) == 1.0  # l'image est intacte


def test_sans_marge_le_calque_est_inchange():
    layer = np.zeros((10, 10), dtype=np.float32)
    assert add_margin_and_marks(layer, marges(margin_mm=0.0)) is layer


def test_les_reperes_sont_dans_la_marge():
    layer = np.zeros((300, 300), dtype=np.float32)
    out = add_margin_and_marks(layer, marges())

    marge = round(5.0 / 25.4 * 600)
    assert float(out.max()) == 1.0  # des repères ont été tracés
    # Rien n'a débordé sur le format utile.
    assert float(out[marge:-marge, marge:-marge].max()) == 0.0


def test_les_reperes_occupent_les_quatre_coins():
    out = add_margin_and_marks(np.zeros((300, 300), dtype=np.float32), marges())
    marge = round(5.0 / 25.4 * 600)

    coins = [
        out[:marge, :marge],
        out[:marge, -marge:],
        out[-marge:, :marge],
        out[-marge:, -marge:],
    ]
    assert all(float(coin.max()) == 1.0 for coin in coins)


def test_les_reperes_tombent_au_pixel_pres_sur_tous_les_calques():
    """Le critère de fin du lot.

    Un décalage d'un seul pixel entre deux calques rendrait les repères
    inutilisables : c'est justement l'écart qu'ils servent à mesurer.
    """
    rng = np.random.default_rng(0)
    formats = marges()

    a = add_margin_and_marks(rng.random((200, 300), dtype=np.float32), formats)
    b = add_margin_and_marks(rng.random((200, 300), dtype=np.float32), formats)

    marge = round(5.0 / 25.4 * 600)
    # Hors du format utile, les deux calques doivent être identiques.
    assert np.array_equal(a[:marge], b[:marge])
    assert np.array_equal(a[-marge:], b[-marge:])
    assert np.array_equal(a[:, :marge], b[:, :marge])
    assert np.array_equal(a[:, -marge:], b[:, -marge:])


def test_reperes_desactivables():
    layer = np.zeros((200, 200), dtype=np.float32)
    out = add_margin_and_marks(layer, marges(registration_marks=False))
    assert float(out.max()) == 0.0


def test_les_reperes_sont_pleins_pas_trames():
    """Un repère tramé serait illisible : il doit être un trait plein."""
    out = add_margin_and_marks(np.zeros((200, 200), dtype=np.float32), marges())
    marge = round(5.0 / 25.4 * 600)
    coin = out[:marge, :marge]
    assert set(np.unique(coin)) == {0.0, 1.0}


def test_le_calque_ecrit_porte_la_marge(tmp_path):
    path = tmp_path / "calque.png"
    write_layer(np.zeros((100, 100), dtype=np.float32), path, marges())

    with Image.open(path) as img:
        marge = round(5.0 / 25.4 * 600)
        assert img.size == (100 + 2 * marge, 100 + 2 * marge)
