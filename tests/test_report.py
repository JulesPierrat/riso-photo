from __future__ import annotations

import numpy as np
import pytest

from src.config import build_profile
from src.project import Project
from src.report import (
    LayerStats,
    format_name,
    layer_stats,
    physical_size_mm,
    render_todo,
)


def duo(**overrides):
    data = {
        "name": "Duotone rose fluo / noir",
        "inks": [
            {"name": "pink", "label": "Fluorescent Pink", "color": "#FF48B0", "order": 1},
            {"name": "black", "label": "Black", "color": "#231F20", "order": 2},
        ],
        "paper": {"color": "#F4EFE2", "label": "Crème 170g"},
        "separation": {
            "method": "duotone",
            "total_ink_limit": 1.7,
            "curves": {"pink": [[0, 0], [1, 1]], "black": [[0, 1], [1, 0]]},
        },
        "halftone": {"method": "clustered-dot", "lpi": 60},
        "output": {"dpi": 600},
    }
    for section, values in overrides.items():
        data[section] = {**data.get(section, {}), **values} if isinstance(values, dict) else values
    return build_profile(data)


def project(tmp_path) -> Project:
    root = tmp_path / "portrait"
    root.mkdir(exist_ok=True)
    source = root / "source.jpg"
    source.write_bytes(b"")
    return Project(name="portrait", root=root, source=source, output_dir=root / "output")


def todo(tmp_path, profile=None, coverage=None, **kwargs) -> str:
    profile = profile or duo()
    if coverage is None:
        coverage = np.full((len(profile.inks), 8, 8), 0.4, dtype=np.float32)

    defaults = dict(
        project=project(tmp_path),
        profile=profile,
        layers=layer_stats(profile, coverage),
        source_px=(3024, 4032),
        output_px=(2480, 3307),
        ink_stats={"total_ink_max": 1.52, "total_ink_mean": 0.9, "limited_fraction": 0.0},
        warnings=(),
        halftoned=True,
    )
    return render_todo(**{**defaults, **kwargs})


# --------------------------------------------------------------------------
# Mesures


def test_taille_physique():
    assert physical_size_mm((3508, 2480), 300) == pytest.approx((297.0, 210.0), abs=0.5)


def test_format_iso_reconnu():
    assert format_name(210, 297) == "A4 portrait"
    assert format_name(297, 210) == "A4 paysage"
    assert format_name(297, 420) == "A3 portrait"


def test_format_non_normalise():
    """Le petit côté suit le ratio de la photo : rien ne garantit un format ISO."""
    assert format_name(297, 223) is None


def test_statistiques_de_calque():
    profile = duo(inks=[
        {"name": "pink", "color": "#FF48B0", "order": 1, "max_coverage": 0.5},
        {"name": "black", "color": "#231F20", "order": 2},
    ])
    coverage = np.zeros((2, 10, 10), dtype=np.float32)
    coverage[0, :5] = 0.5  # la moitié du calque au plafond
    coverage[1] = 0.2

    stats = layer_stats(profile, coverage)

    assert stats[0].file == "01_pink.png"
    assert stats[0].coverage_max == pytest.approx(0.5)
    assert stats[0].capped_fraction == pytest.approx(0.5)
    assert stats[1].capped_fraction == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Structure du plan


def test_entete(tmp_path):
    texte = todo(tmp_path)
    assert texte.startswith("# portrait — plan d'impression")
    assert "Profil : Duotone rose fluo / noir" in texte
    assert "source.jpg (3024 × 4032)" in texte
    assert "Crème 170g" in texte


def test_encrage_dans_lentete(tmp_path):
    assert "152 % (limite du profil : 170 %) ✅" in todo(tmp_path)


def test_depassement_dencrage_signale(tmp_path):
    texte = todo(
        tmp_path,
        ink_stats={"total_ink_max": 1.9, "total_ink_mean": 1.0, "limited_fraction": 0.2},
    )
    assert "190 % (limite du profil : 170 %) ⚠️" in texte


def test_un_bloc_par_passage(tmp_path):
    texte = todo(tmp_path)
    assert "### Passage 1 — Fluorescent Pink" in texte
    assert "### Passage 2 — Black" in texte
    assert texte.index("Passage 1") < texte.index("Passage 2")


def test_fichiers_et_couvertures(tmp_path):
    texte = todo(tmp_path)
    assert "`01_pink.png`" in texte
    assert "`02_black.png`" in texte
    assert "Couverture moyenne : 40 %" in texte


def test_format_iso_annonce(tmp_path):
    # 2480 × 3508 px, c'est A4 à 300 dpi — mais A6 à 600 dpi.
    a4 = todo(tmp_path, profile=duo(output={"dpi": 300}), output_px=(2480, 3508))
    assert "A4 portrait" in a4

    a6 = todo(tmp_path, output_px=(2480, 3508))  # le profil est à 600 dpi
    assert "A6 portrait" in a6


# --------------------------------------------------------------------------
# Trame


def test_trame_am_detaillee(tmp_path):
    texte = todo(tmp_path)
    assert "points agglomérés round, 60 lpi, 15°" in texte
    assert "45°" in texte


def test_ton_continu_quand_le_tramage_na_pas_eu_lieu(tmp_path):
    """Le plan décrit les fichiers produits, pas les intentions du profil."""
    texte = todo(tmp_path, halftoned=False)
    assert "ton continu" in texte
    assert "points agglomérés" not in texte


def test_diffusion_derreur(tmp_path):
    texte = todo(tmp_path, profile=duo(halftone={"method": "error-diffusion"}))
    assert "diffusion d'erreur" in texte


# --------------------------------------------------------------------------
# Notes contextuelles


def test_note_sur_lencre_claire_en_premier(tmp_path):
    assert "encre la plus claire imprimée en premier" in todo(tmp_path)


def test_ordre_de_passage_inhabituel_signale(tmp_path):
    """Imprimer le foncé en premier est possible, mais mérite une question."""
    inverse = duo(
        inks=[
            {"name": "black", "label": "Black", "color": "#231F20", "order": 1},
            {"name": "pink", "label": "Fluorescent Pink", "color": "#FF48B0", "order": 2},
        ],
        separation={
            "method": "duotone",
            "total_ink_limit": 1.7,
            "curves": {"pink": [[0, 0], [1, 1]], "black": [[0, 1], [1, 0]]},
        },
    )
    texte = todo(tmp_path, profile=inverse)
    assert "n'est pas l'encre la plus claire" in texte


def test_note_sur_lencre_qui_porte_le_contraste(tmp_path):
    assert "c'est elle qui porte le contraste" in todo(tmp_path)


def test_passage_a_couverture_negligeable(tmp_path):
    coverage = np.full((2, 8, 8), 0.4, dtype=np.float32)
    coverage[0] = 0.01

    texte = todo(tmp_path, coverage=coverage)
    assert "envisager de le supprimer du profil" in texte


def test_plafond_configure_atteint(tmp_path):
    bride = duo(inks=[
        {"name": "pink", "label": "Pink", "color": "#FF48B0", "order": 1, "max_coverage": 0.4},
        {"name": "black", "label": "Black", "color": "#231F20", "order": 2},
    ])
    coverage = np.full((2, 8, 8), 0.4, dtype=np.float32)

    texte = todo(tmp_path, profile=bride, coverage=coverage)
    assert "Relever `max_coverage`" in texte


def test_encre_a_fond_sans_plafond_configure(tmp_path):
    """À 100 %, conseiller de relever le plafond n'aurait aucun sens."""
    coverage = np.ones((2, 8, 8), dtype=np.float32)

    texte = todo(tmp_path, coverage=coverage)
    assert "densité maximale qu'elle puisse donner" in texte
    assert "Relever `max_coverage`" not in texte


# --------------------------------------------------------------------------
# Points de vigilance


def test_consignes_multipassage(tmp_path):
    texte = todo(tmp_path)
    assert "Laisser sécher **au moins 2 h**" in texte
    assert "tolérance risographe" in texte
    assert "Charger tout le papier en une seule fois" in texte


def test_pas_de_consignes_de_reperage_en_monochrome(tmp_path):
    mono = build_profile(
        {
            "name": "mono",
            "inks": [{"name": "black", "label": "Black", "color": "#231F20"}],
            "separation": {"method": "luminance"},
        }
    )
    texte = todo(tmp_path, profile=mono, coverage=np.full((1, 8, 8), 0.4, dtype=np.float32))
    assert "Laisser sécher" not in texte
    assert "tolérance risographe" not in texte


def test_absence_de_reperes_signalee(tmp_path):
    texte = todo(tmp_path, profile=duo(output={"registration_marks": False}))
    assert "le calage se fera à vue" in texte


def test_verdict_de_moire_favorable(tmp_path):
    assert "pas de risque de moiré" in todo(tmp_path)


def test_avertissement_de_moire_remplace_le_verdict(tmp_path):
    texte = todo(tmp_path, warnings=["angles de trame : … risque de moiré …"])
    assert "pas de risque de moiré" not in texte
    assert "risque de moiré" in texte


def test_les_avertissements_du_run_sont_repris(tmp_path):
    """Ils doivent atteindre la personne qui imprime, pas seulement celle qui calcule."""
    texte = todo(tmp_path, warnings=["sous-résolution : …", "dpi/lpi = 5.0 …"])
    assert "sous-résolution" in texte
    assert "dpi/lpi" in texte


def test_pied_de_page(tmp_path):
    assert "Paramètres exacts dans `run.json`" in todo(tmp_path)


def test_markdown_termine_par_un_saut_de_ligne(tmp_path):
    assert todo(tmp_path).endswith("\n")


def test_plafonnement_dencrage_signale(tmp_path):
    """Une limite qui mord partout bride la séparation plus que le papier."""
    texte = todo(
        tmp_path,
        ink_stats={"total_ink_max": 1.7, "total_ink_mean": 1.5, "limited_fraction": 0.52},
    )
    assert "plafonné sur 52 % de l'image" in texte
    assert "Black" in texte


def test_plafonnement_marginal_non_signale(tmp_path):
    texte = todo(
        tmp_path,
        ink_stats={"total_ink_max": 1.7, "total_ink_mean": 0.9, "limited_fraction": 0.01},
    )
    assert "plafonné sur" not in texte
