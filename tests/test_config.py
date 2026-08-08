"""Une règle de validation = un test. Voir doc/config.md pour la référence."""

from __future__ import annotations

import json

import pytest

from src.config import (
    angle_spread,
    build_profile,
    default_screen_angles,
    load_profile,
    resolve_config_path,
)
from src.errors import ProfileError, UsageError


def problems(data: dict) -> list[str]:
    with pytest.raises(ProfileError) as excinfo:
        build_profile(data)
    return list(excinfo.value.problems)


def assert_faute(data: dict, fragment: str) -> None:
    found = problems(data)
    assert any(fragment in p for p in found), f"{fragment!r} absent de {found}"


# --------------------------------------------------------------------------
# Cas nominal et valeurs par défaut


def test_profil_minimal_valide(profile_data):
    profile = build_profile(profile_data)
    assert profile.name == "Test duotone"
    assert [ink.name for ink in profile.inks] == ["pink", "black"]
    assert profile.warnings == ()


def test_valeurs_par_defaut(profile_data):
    profile = build_profile(profile_data)
    assert profile.output.format == "png"
    assert profile.output.bit_depth == 8
    assert profile.output.invert is False
    assert profile.output.long_edge_mm == 297.0
    assert profile.separation.preserve_highlights is True
    assert profile.tone.is_identity
    assert profile.paper.color_hex == "#FFFFFF"


def test_encres_triees_par_ordre_de_passage(profile_data):
    profile_data["inks"][0]["order"] = 2
    profile_data["inks"][1]["order"] = 1
    profile = build_profile(profile_data)
    assert [ink.name for ink in profile.inks] == ["black", "pink"]
    assert [ink.order for ink in profile.inks] == [1, 2]


def test_label_par_defaut_vaut_le_nom(profile_data):
    assert build_profile(profile_data).inks[0].label == "pink"


def test_encre_la_plus_foncee(profile_data):
    assert build_profile(profile_data).darkest_ink.name == "black"


def test_angles_par_defaut_appliques(profile_data):
    for ink in profile_data["inks"]:
        del ink["screen_angle"]
    profile = build_profile(profile_data)
    # 45° revient au dernier passage, l'encre la plus foncée.
    assert [ink.screen_angle for ink in profile.inks] == [15.0, 45.0]


# --------------------------------------------------------------------------
# Erreurs bloquantes


def test_inks_manquant(profile_data):
    del profile_data["inks"]
    assert_faute(profile_data, "inks : champ requis manquant")


def test_inks_vide(profile_data):
    profile_data["inks"] = []
    assert_faute(profile_data, "liste non vide")


def test_couleur_manquante(profile_data):
    del profile_data["inks"][0]["color"]
    assert_faute(profile_data, "inks[0].color : champ requis manquant")


def test_couleur_mal_formee(profile_data):
    profile_data["inks"][0]["color"] = "#ZZZ"
    assert_faute(profile_data, "mal formée")


def test_nom_dencre_duplique(profile_data):
    profile_data["inks"][1]["name"] = "pink"
    assert_faute(profile_data, "nom d'encre dupliqué")


def test_ordre_duplique(profile_data):
    profile_data["inks"][1]["order"] = 1
    assert_faute(profile_data, "ordres de passage dupliqués")


def test_ordre_non_contigu(profile_data):
    profile_data["inks"][1]["order"] = 5
    assert_faute(profile_data, "contigu à partir de 1")


@pytest.mark.parametrize("value", [-0.1, 1.5])
def test_opacite_hors_bornes(profile_data, value):
    profile_data["inks"][0]["opacity"] = value
    assert_faute(profile_data, "opacity")


def test_gamma_nul(profile_data):
    profile_data["tone"] = {"gamma": 0}
    assert_faute(profile_data, "gamma")


def test_point_noir_au_dessus_du_point_blanc(profile_data):
    profile_data["tone"] = {"black_point": 0.8, "white_point": 0.2}
    assert_faute(profile_data, "black_point")


def test_methode_de_separation_inconnue(profile_data):
    profile_data["separation"]["method"] = "magie"
    assert_faute(profile_data, "valeur inconnue")


def test_nombre_dencres_incompatible(profile_data):
    profile_data["separation"] = {"method": "luminance"}
    assert_faute(profile_data, "exige 1 encre(s)")


def test_duotone_sans_courbes(profile_data):
    del profile_data["separation"]["curves"]
    assert_faute(profile_data, "curves : requis")


def test_courbe_manquante_pour_une_encre(profile_data):
    del profile_data["separation"]["curves"]["black"]
    assert_faute(profile_data, "courbe manquante pour 'black'")


def test_courbe_pour_une_encre_inexistante(profile_data):
    profile_data["separation"]["curves"]["bleu"] = [[0, 0], [1, 1]]
    assert_faute(profile_data, "aucune encre nommée 'bleu'")


def test_courbe_non_croissante(profile_data):
    profile_data["separation"]["curves"]["pink"] = [[0.5, 0.0], [0.2, 1.0]]
    assert_faute(profile_data, "strictement croissantes")


def test_courbe_hors_bornes(profile_data):
    profile_data["separation"]["curves"]["pink"] = [[0.0, 0.0], [1.0, 1.4]]
    assert_faute(profile_data, "hors de [0, 1]")


def test_lpi_negatif(profile_data):
    profile_data["halftone"]["lpi"] = -10
    assert_faute(profile_data, "lpi")


def test_toutes_les_erreurs_sont_remontees(profile_data):
    """Corriger un JSON erreur par erreur est pénible : on les liste toutes."""
    profile_data["inks"][0]["color"] = "nope"
    profile_data["inks"][0]["opacity"] = 3
    profile_data["halftone"]["lpi"] = 0
    assert len(problems(profile_data)) >= 3


def test_code_de_sortie_du_profil_invalide(profile_data):
    del profile_data["inks"]
    with pytest.raises(ProfileError) as excinfo:
        build_profile(profile_data)
    assert excinfo.value.code == 2


# --------------------------------------------------------------------------
# Avertissements — n'interrompent jamais


def test_angles_trop_proches(profile_data):
    profile_data["inks"][1]["screen_angle"] = 20
    profile = build_profile(profile_data)
    assert any("moiré" in w for w in profile.warnings)


def test_periodicite_des_angles_a_90_degres(profile_data):
    """5° et 95° sont le même angle de trame."""
    profile_data["inks"][0]["screen_angle"] = 5
    profile_data["inks"][1]["screen_angle"] = 95
    profile = build_profile(profile_data)
    assert any("moiré" in w for w in profile.warnings)


def test_pas_davertissement_dangle_hors_trame_am(profile_data):
    profile_data["inks"][1]["screen_angle"] = 20
    profile_data["halftone"]["method"] = "error-diffusion"
    assert not any("moiré" in w for w in build_profile(profile_data).warnings)


def test_rapport_dpi_lpi_insuffisant(profile_data):
    profile_data["output"]["dpi"] = 300
    profile_data["halftone"]["lpi"] = 60
    profile = build_profile(profile_data)
    assert any("dpi/lpi" in w for w in profile.warnings)


def test_encrage_total_excessif(profile_data):
    profile_data["separation"]["total_ink_limit"] = 3.0
    assert any("saturation" in w for w in build_profile(profile_data).warnings)


def test_16_bits_sans_effet_avec_tramage(profile_data):
    profile_data["output"]["bit_depth"] = 16
    assert any("binaire" in w for w in build_profile(profile_data).warnings)


def test_encre_proche_du_papier(profile_data):
    profile_data["inks"][0]["color"] = "#FEFEFE"
    assert any("papier" in w for w in build_profile(profile_data).warnings)


def test_cle_inconnue_signalee(profile_data):
    profile_data["output"]["dip"] = 300
    assert any("dip" in w for w in build_profile(profile_data).warnings)


# --------------------------------------------------------------------------
# Angles


def test_angle_spread_periodique():
    assert angle_spread(15, 45) == pytest.approx(30)
    assert angle_spread(5, 95) == pytest.approx(0)
    assert angle_spread(0, 75) == pytest.approx(15)


def test_angles_par_defaut_ecartes_pour_deux_et_trois_encres():
    for count in (2, 3):
        angles = default_screen_angles(count)
        assert len(angles) == count
        for i, first in enumerate(angles):
            for second in angles[i + 1 :]:
                assert angle_spread(first, second) >= 15


def test_quatre_encres_zero_degre_au_premier_passage():
    """L'encre la plus claire encaisse le moiré résiduel."""
    assert default_screen_angles(4)[0] == 0.0
    assert default_screen_angles(4)[-1] == 45.0


# --------------------------------------------------------------------------
# Résolution et fusion


def test_resolution_nom_court(workspace, monkeypatch):
    monkeypatch.chdir(workspace)
    assert resolve_config_path("test").name == "test.json"
    assert resolve_config_path("test.json").name == "test.json"


def test_resolution_par_chemin(workspace, monkeypatch):
    monkeypatch.chdir(workspace)
    assert resolve_config_path("./config/test.json").is_file()


def test_profil_introuvable_liste_les_disponibles(workspace, monkeypatch):
    monkeypatch.chdir(workspace)
    with pytest.raises(UsageError) as excinfo:
        resolve_config_path("absent")
    assert "test" in str(excinfo.value)
    assert excinfo.value.code == 1


def test_json_invalide(workspace, monkeypatch):
    monkeypatch.chdir(workspace)
    (workspace / "config" / "casse.json").write_text("{ pas du json", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile("casse")


def test_fusion_du_config_local(workspace, monkeypatch):
    monkeypatch.chdir(workspace)
    demo = workspace / "project" / "demo"
    (demo / "config.json").write_text(
        json.dumps({"output": {"dpi": 1200}}), encoding="utf-8"
    )
    profile = load_profile("test", project_dir=demo)
    assert profile.output.dpi == 1200
    # La fusion est profonde : les autres champs de `output` survivent.
    assert profile.output.long_edge_mm == 297.0
    assert any("config.json" in s for s in profile.sources)


def test_surcharges_cli_appliquees_en_dernier(workspace, monkeypatch):
    monkeypatch.chdir(workspace)
    demo = workspace / "project" / "demo"
    (demo / "config.json").write_text(
        json.dumps({"output": {"dpi": 1200}}), encoding="utf-8"
    )
    profile = load_profile(
        "test", project_dir=demo, overrides={"output": {"dpi": 150}}
    )
    assert profile.output.dpi == 150


def test_les_listes_sont_remplacees_pas_concatenees(workspace, monkeypatch):
    monkeypatch.chdir(workspace)
    demo = workspace / "project" / "demo"
    (demo / "config.json").write_text(
        json.dumps(
            {
                "inks": [{"name": "black", "color": "#000000", "order": 1}],
                "separation": {"method": "luminance", "curves": None},
            }
        ),
        encoding="utf-8",
    )
    assert len(load_profile("test", project_dir=demo).inks) == 1


# --------------------------------------------------------------------------
# Profils livrés


@pytest.mark.parametrize("name", ["mono-noir", "duotone-rose-noir"])
def test_les_profils_livres_sont_valides_et_sans_avertissement(name):
    profile = load_profile(name)
    assert profile.warnings == (), f"{name} : {profile.warnings}"
