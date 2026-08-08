from __future__ import annotations

import numpy as np
import pytest

from src.color import LUMA_COEFFS, hex_to_linear, linear_to_srgb, srgb_to_linear
from src.config import build_profile, load_profile
from src.errors import NotImplementedYet, ProfileError
from src.preview import composite
from src.image import relative_luminance
from src.inks import transmittance
from src.separation import (
    HIGHLIGHT_FLOOR,
    apply_curve,
    limit_ink,
    separate,
    solve_bounded_lsq,
)


def flat(value: float, size: int = 8) -> np.ndarray:
    """Aplat uni `(size, size, 3)` linéaire, décrit en sRVB encodé."""
    return srgb_to_linear(np.full((size, size, 3), value, dtype=np.float32))


def ramp(width: int = 256) -> np.ndarray:
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)
    return srgb_to_linear(np.repeat(x.reshape(1, width, 1), 3, axis=2))


def mono_profile(**separation) -> object:
    return build_profile(
        {
            "name": "mono",
            "inks": [{"name": "black", "color": "#231F20", "opacity": 1.0}],
            "separation": {"method": "luminance", **separation},
            "halftone": {"method": "none"},
        }
    )


def duo_profile(**separation) -> object:
    base = {
        "method": "duotone",
        "curves": {
            "pink": [[0.0, 0.0], [0.5, 0.9], [1.0, 0.0]],
            "black": [[0.0, 1.0], [0.5, 0.4], [1.0, 0.0]],
        },
    }
    return build_profile(
        {
            "name": "duo",
            "inks": [
                {"name": "pink", "color": "#FF48B0", "order": 1},
                {"name": "black", "color": "#231F20", "order": 2},
            ],
            "separation": {**base, **separation},
            "halftone": {"method": "none"},
        }
    )


def overprint(coverage: np.ndarray, profile) -> np.ndarray:
    """Modèle de surimpression de doc/separation.md, pour vérifier l'inversion."""
    out = np.broadcast_to(profile.paper.color, (*coverage.shape[1:], 3)).copy()
    for index, ink in enumerate(profile.inks):
        factor = 1.0 - coverage[index][..., np.newaxis] * (1.0 - transmittance(ink))
        out = out * factor
    return out


# --------------------------------------------------------------------------
# Courbes de réponse


def test_courbe_passe_par_ses_points():
    points = [[0.0, 0.0], [0.5, 0.9], [1.0, 0.0]]
    x = np.array([0.0, 0.5, 1.0], dtype=np.float32)
    assert np.allclose(apply_curve(x, points), [0.0, 0.9, 0.0], atol=1e-3)


def test_courbe_interpole_lineairement():
    points = [[0.0, 0.0], [1.0, 1.0]]
    x = np.array([0.25, 0.75], dtype=np.float32)
    assert np.allclose(apply_curve(x, points), [0.25, 0.75], atol=1e-3)


def test_courbe_fidele_a_la_reference():
    """La table doit coller à l'interpolation exacte."""
    points = [[0.0, 0.1], [0.35, 0.85], [0.75, 0.45], [1.0, 0.0]]
    x = np.linspace(0.0, 1.0, 2048, dtype=np.float32)

    exact = np.interp(x, [p[0] for p in points], [p[1] for p in points])
    assert float(np.abs(apply_curve(x, points) - exact).max()) < 1e-3


def test_courbe_ecrete_les_entrees_hors_bornes():
    points = [[0.0, 0.2], [1.0, 0.8]]
    x = np.array([-0.5, 1.5], dtype=np.float32)
    assert np.allclose(apply_curve(x, points), [0.2, 0.8], atol=1e-3)


def test_courbe_rend_du_float32():
    assert apply_curve(np.zeros((4, 4), dtype=np.float32), [[0, 0], [1, 1]]).dtype == np.float32


# --------------------------------------------------------------------------
# Méthode `luminance`


def test_luminance_forme_et_bornes():
    coverage, _ = separate(ramp(), mono_profile())
    assert coverage.shape == (1, 1, 256)
    assert coverage.min() >= 0.0 and coverage.max() <= 1.0
    assert coverage.dtype == np.float32


def test_luminance_papier_nu_sur_le_blanc():
    coverage, _ = separate(flat(1.0), mono_profile())
    assert float(coverage.max()) == pytest.approx(0.0, abs=1e-4)


def test_luminance_encre_pleine_sur_le_noir():
    coverage, _ = separate(flat(0.0), mono_profile(total_ink_limit=1.0))
    assert float(coverage.min()) == pytest.approx(1.0, abs=1e-3)


def test_luminance_croit_avec_lobscurite():
    coverage, _ = separate(ramp(), mono_profile(preserve_highlights=False))
    assert np.all(np.diff(coverage[0, 0]) <= 1e-6)


def test_luminance_inverse_bien_le_modele():
    """La surimpression du calque doit redonner la luminance de la source.

    C'est le test qui justifie de ne pas séparer sur `1 − luminance perceptuelle` :
    seule l'inversion du modèle garantit que l'aperçu correspondra au calque.
    """
    profile = mono_profile(preserve_highlights=False, total_ink_limit=1.0)
    source = ramp(64)

    coverage, _ = separate(source, profile)
    rendered = overprint(coverage, profile)

    # Hors des tons que l'encre ne peut pas atteindre (plus sombres que son aplat).
    reachable = relative_luminance(source) > 0.02
    ecart = np.abs(relative_luminance(rendered) - relative_luminance(source))
    assert float(ecart[reachable].max()) < 0.01


def test_luminance_tient_compte_du_papier_creme():
    """Sur papier teinté, le blanc de la photo reste du papier nu."""
    profile = build_profile(
        {
            "name": "creme",
            "inks": [{"name": "black", "color": "#231F20"}],
            "paper": {"color": "#F4EFE2"},
            "separation": {"method": "luminance"},
        }
    )
    coverage, _ = separate(flat(1.0), profile)
    assert float(coverage.max()) == pytest.approx(0.0, abs=1e-4)


# --------------------------------------------------------------------------
# Méthode `duotone`


def test_duotone_forme():
    coverage, _ = separate(ramp(), duo_profile())
    assert coverage.shape == (2, 1, 256)


def test_duotone_suit_les_courbes():
    """Le noir tient les ombres, le rose les demi-teintes."""
    coverage, _ = separate(flat(0.0), duo_profile())
    ombres_rose, ombres_noir = float(coverage[0].mean()), float(coverage[1].mean())

    coverage, _ = separate(flat(0.5), duo_profile())
    moyens_rose = float(coverage[0].mean())

    assert ombres_noir > ombres_rose
    assert moyens_rose > ombres_rose


def test_duotone_ignore_la_chromie():
    """Parti pris assumé : deux couleurs de même luminance se séparent pareil."""
    cible = 0.2126  # ce que donne un rouge saturé, atteignable aussi en vert

    rouge = np.zeros((4, 4, 3), dtype=np.float32)
    rouge[..., 0] = cible / LUMA_COEFFS[0]
    vert = np.zeros((4, 4, 3), dtype=np.float32)
    vert[..., 1] = cible / LUMA_COEFFS[1]

    assert float(relative_luminance(rouge).mean()) == pytest.approx(cible, abs=1e-4)
    assert float(relative_luminance(vert).mean()) == pytest.approx(cible, abs=1e-4)

    a, _ = separate(rouge, duo_profile())
    b, _ = separate(vert, duo_profile())
    assert np.allclose(a, b, atol=1e-3)


def test_tritone_accepte_trois_encres():
    profile = build_profile(
        {
            "name": "tri",
            "inks": [
                {"name": "yellow", "color": "#FFE800", "order": 1},
                {"name": "pink", "color": "#FF48B0", "order": 2},
                {"name": "black", "color": "#231F20", "order": 3},
            ],
            "separation": {
                "method": "tritone",
                "total_ink_limit": 2.0,
                "curves": {
                    "yellow": [[0.0, 0.0], [0.6, 0.7], [1.0, 0.0]],
                    "pink": [[0.0, 0.2], [0.4, 0.8], [1.0, 0.0]],
                    "black": [[0.0, 1.0], [0.5, 0.3], [1.0, 0.0]],
                },
            },
        }
    )
    coverage, _ = separate(ramp(), profile)
    assert coverage.shape == (3, 1, 256)


# --------------------------------------------------------------------------
# Méthodes non écrites


@pytest.mark.parametrize("method", ["cmyk"])
def test_methodes_non_ecrites(method):
    profile = build_profile(
        {
            "name": "x",
            "inks": [
                {"name": "pink", "color": "#FF48B0", "order": 1},
                {"name": "blue", "color": "#0078BF", "order": 2},
                {"name": "black", "color": "#231F20", "order": 3},
            ],
            "separation": {"method": method},
        }
    )
    with pytest.raises(NotImplementedYet, match="doc/plan.md"):
        separate(ramp(), profile)


# --------------------------------------------------------------------------
# Hautes lumières


def test_preserve_highlights_nettoie_les_traces():
    profile = duo_profile(preserve_highlights=True)
    coverage, _ = separate(ramp(), profile)
    trace = (coverage > 0.0) & (coverage < HIGHLIGHT_FLOOR)
    assert not trace.any()


def test_sans_preserve_highlights_les_traces_subsistent():
    coverage, _ = separate(ramp(), duo_profile(preserve_highlights=False))
    assert ((coverage > 0.0) & (coverage < HIGHLIGHT_FLOOR)).any()


# --------------------------------------------------------------------------
# Limitation d'encrage


def test_plafond_par_encre():
    profile = build_profile(
        {
            "name": "plafond",
            "inks": [{"name": "black", "color": "#231F20", "max_coverage": 0.6}],
            "separation": {"method": "luminance"},
        }
    )
    coverage, _ = separate(flat(0.0), profile)
    assert float(coverage.max()) <= 0.6 + 1e-6


def test_encrage_total_respecte():
    profile = duo_profile(total_ink_limit=0.9)
    coverage, stats = separate(ramp(), profile)

    assert float(coverage.sum(axis=0).max()) <= 0.9 + 1e-4
    assert stats["total_ink_max"] <= 0.9 + 1e-4


def test_la_limite_reporte_vers_lencre_foncee():
    """Réduire les claires et compenser en foncé, plutôt qu'écrêter à plat."""
    source = flat(0.15)  # ombre : les deux encres sont sollicitées

    brut, _ = separate(source, duo_profile(total_ink_limit=10.0, preserve_highlights=False))
    limite, _ = separate(source, duo_profile(total_ink_limit=1.0, preserve_highlights=False))

    assert float(limite[0].mean()) < float(brut[0].mean())  # le rose recule
    assert float(limite[1].mean()) > float(brut[1].mean())  # le noir compense
    assert float(limite.sum(axis=0).max()) == pytest.approx(1.0, abs=1e-3)


def test_limite_sous_lencre_foncee_seule():
    """Rien à reporter quand la limite est plus basse que l'encre foncée seule.

    Le report ne peut pas aider : on retombe sur une réduction uniforme, et
    l'invariant tient quand même.
    """
    source = flat(0.15)
    brut, _ = separate(source, duo_profile(total_ink_limit=10.0, preserve_highlights=False))
    assert float(brut[1].max()) > 0.8  # le noir dépasse à lui seul la limite visée

    limite, _ = separate(source, duo_profile(total_ink_limit=0.8, preserve_highlights=False))
    assert float(limite.sum(axis=0).max()) <= 0.8 + 1e-4
    assert float(limite[0].max()) == pytest.approx(0.0, abs=1e-6)


def test_limite_non_atteinte_ne_change_rien():
    profile = duo_profile(total_ink_limit=10.0)
    coverage, stats = separate(ramp(), profile)
    assert stats["limited_fraction"] == 0.0


def test_statistiques_dencrage():
    _, stats = separate(ramp(), duo_profile(total_ink_limit=0.9))
    assert set(stats) == {"total_ink_max", "total_ink_mean", "limited_fraction"}
    assert 0.0 <= stats["limited_fraction"] <= 1.0
    assert stats["total_ink_mean"] <= stats["total_ink_max"]


def test_limit_ink_seul_respecte_la_limite():
    profile = duo_profile(total_ink_limit=1.2)
    sature = np.ones((2, 16, 16), dtype=np.float32)

    limite, stats = limit_ink(sature, profile)
    assert float(limite.sum(axis=0).max()) <= 1.2 + 1e-4
    assert stats["limited_fraction"] == pytest.approx(1.0)


def test_limit_ink_avec_une_seule_encre():
    profile = mono_profile(total_ink_limit=0.5)
    limite, _ = limit_ink(np.ones((1, 4, 4), dtype=np.float32), profile)
    assert float(limite.max()) <= 0.5 + 1e-6


# --------------------------------------------------------------------------
# Solveur de moindres carrés bornés


def test_solveur_respecte_les_bornes():
    rng = np.random.default_rng(0)
    matrix = rng.normal(size=(3, 3)).astype(np.float32)
    caps = np.array([0.9, 0.7, 1.0], dtype=np.float32)
    rhs = rng.normal(scale=3.0, size=(3, 500)).astype(np.float32)

    solved = solve_bounded_lsq(matrix, rhs, caps)

    assert solved.shape == (3, 500)
    assert float(solved.min()) >= -1e-6
    assert np.all(solved <= caps[:, None] + 1e-6)


def test_solveur_exact_face_a_une_recherche_exhaustive():
    """L'énumération des jeux actifs doit rendre l'optimum, pas une approximation."""
    rng = np.random.default_rng(3)
    matrix = rng.normal(size=(3, 2)).astype(np.float32)
    caps = np.array([0.8, 0.6], dtype=np.float32)
    rhs = rng.normal(scale=2.0, size=(3, 30)).astype(np.float32)

    solved = solve_bounded_lsq(matrix, rhs, caps)

    grid = np.stack(
        np.meshgrid(np.linspace(0, caps[0], 120), np.linspace(0, caps[1], 120)),
        axis=-1,
    ).reshape(-1, 2)
    brute = ((matrix @ grid.T)[:, :, None] - rhs[:, None, :]) ** 2
    meilleur = brute.sum(axis=0).min(axis=0)

    obtenu = np.sum((matrix @ solved - rhs) ** 2, axis=0)
    assert np.all(obtenu <= meilleur + 1e-4)


def test_solveur_sans_contrainte_active():
    """Quand l'optimum libre tient dans les bornes, c'est lui la réponse."""
    matrix = np.eye(3, dtype=np.float32)
    caps = np.ones(3, dtype=np.float32)
    rhs = np.array([[0.2], [0.5], [0.8]], dtype=np.float32)

    assert np.allclose(solve_bounded_lsq(matrix, rhs, caps), rhs, atol=1e-6)


def test_solveur_avec_encres_colineaires():
    """Deux encres identiques rendent le système dégénéré : pas de plantage."""
    matrix = np.array([[1.0, 1.0], [0.5, 0.5], [0.2, 0.2]], dtype=np.float32)
    caps = np.ones(2, dtype=np.float32)
    rhs = np.array([[1.0], [0.5], [0.2]], dtype=np.float32)

    solved = solve_bounded_lsq(matrix, rhs, caps)
    assert np.isfinite(solved).all()
    assert float(np.sum((matrix @ solved - rhs) ** 2)) < 1e-4


def test_decoupage_en_blocs_sans_effet(monkeypatch):
    """Le découpage borne la mémoire ; il ne doit rien changer au résultat."""
    profile = load_profile("trichro-cmj")
    rng = np.random.default_rng(5)
    img = rng.random((40, 40, 3), dtype=np.float32)

    entier, _ = separate(img, profile)
    monkeypatch.setattr("src.separation._SOLVER_CHUNK", 137)
    morcele, _ = separate(img, profile)

    assert np.allclose(entier, morcele, atol=1e-6)


def test_trop_dencres_pour_lenumeration():
    inks = [
        {"name": f"e{i}", "color": c, "order": i + 1}
        for i, c in enumerate(
            ["#FFE800", "#FF48B0", "#0078BF", "#00A95C", "#FF6F61", "#231F20"]
        )
    ]
    profile = build_profile(
        {"name": "six", "inks": inks, "separation": {"method": "density-lsq"}}
    )
    with pytest.raises(ProfileError, match="jusqu'à 5 encres"):
        separate(ramp(), profile)


# --------------------------------------------------------------------------
# Méthode `density-lsq`


def trichro(**separation):
    return load_profile(
        "trichro-cmj", overrides={"separation": separation} if separation else None
    )


def test_density_lsq_forme_et_bornes():
    profile = trichro()
    coverage, _ = separate(ramp(), profile)

    assert coverage.shape == (3, 1, 256)
    assert coverage.dtype == np.float32
    assert coverage.min() >= 0.0 and coverage.max() <= 1.0


def test_density_lsq_papier_nu_sur_le_blanc():
    coverage, _ = separate(flat(1.0), trichro())
    assert float(coverage.max()) == pytest.approx(0.0, abs=1e-3)


def test_density_lsq_reproduit_mieux_quun_duotone():
    """Critère de fin du lot : la séparation générale doit valoir son coût."""
    mire = np.stack(
        [
            hex_to_linear(c)
            for c in ("#E8B89B", "#C68642", "#808080", "#4A7BA7", "#7BA05B", "#F5D76E")
        ]
    ).reshape(1, -1, 3)

    duo = load_profile("duotone-rose-noir", overrides={"paper": {"color": "#FFFFFF"}})
    ecarts = {}
    for nom, profile in (("duotone", duo), ("density-lsq", trichro())):
        coverage, _ = separate(mire, profile)
        rendu = composite(coverage, profile)
        ecarts[nom] = float(np.abs(linear_to_srgb(rendu) - linear_to_srgb(mire)).mean())

    assert ecarts["density-lsq"] < ecarts["duotone"]
    assert ecarts["density-lsq"] < 0.12


def test_density_lsq_preserve_la_teinte_hors_gamut():
    """Une cible inatteignable doit rester du bon côté de la roue.

    Sans plafonnement de la densité cible, le solveur saturait l'encre bleue
    pour gratter un résidu impossible et rendait un rouge pur en gris-bleu.
    """
    profile = trichro()
    rouge = np.array([[[1.0, 0.0, 0.0]]], dtype=np.float32)

    coverage, _ = separate(rouge, profile)
    rendu = composite(coverage, profile)[0, 0]

    assert float(rendu[0]) > float(rendu[1])
    assert float(rendu[0]) > float(rendu[2])


def test_density_lsq_tient_compte_du_papier():
    creme = load_profile("trichro-cmj", overrides={"paper": {"color": "#F4EFE2"}})
    coverage, _ = separate(flat(1.0), creme)
    assert float(coverage.max()) == pytest.approx(0.0, abs=1e-3)


def test_black_generation_favorise_lencre_foncee():
    """Avec quatre encres le système est sous-déterminé : la pénalité tranche."""
    quatre = {
        "name": "quadri",
        "inks": [
            {"name": "yellow", "color": "#FFE800", "order": 1},
            {"name": "pink", "color": "#FF48B0", "order": 2},
            {"name": "blue", "color": "#0078BF", "order": 3},
            {"name": "black", "color": "#231F20", "order": 4},
        ],
        "separation": {"method": "density-lsq", "total_ink_limit": 3.0},
    }
    gris = srgb_to_linear(np.full((1, 4, 3), 0.35, dtype=np.float32))

    faible, _ = separate(gris, build_profile(
        {**quatre, "separation": {**quatre["separation"], "black_generation": 0.0}}))
    fort, _ = separate(gris, build_profile(
        {**quatre, "separation": {**quatre["separation"], "black_generation": 1.0}}))

    assert float(fort[3].mean()) > float(faible[3].mean())      # plus de noir
    assert float(fort.sum(axis=0).mean()) < float(faible.sum(axis=0).mean())  # moins d'encre


def test_solveur_conforme_a_scipy():
    """Référence indépendante.

    SciPy résout un problème à la fois — inutilisable sur des dizaines de
    millions de pixels — mais c'est exactement ce qui en fait un bon juge.
    L'import est local : sans SciPy, seul ce test est sauté.
    """
    scipy_optimize = pytest.importorskip("scipy.optimize", reason="SciPy absent")
    rng = np.random.default_rng(7)
    pire = 0.0

    for _ in range(25):
        count = int(rng.integers(2, 6))
        matrix = rng.normal(size=(3, count)).astype(np.float32)
        caps = rng.uniform(0.4, 1.0, size=count).astype(np.float32)
        rhs = rng.normal(scale=2.0, size=(3, 40)).astype(np.float32)

        mine = solve_bounded_lsq(matrix, rhs, caps)
        for column in range(rhs.shape[1]):
            reference = scipy_optimize.lsq_linear(
                matrix, rhs[:, column], bounds=(0.0, caps), method="bvls"
            ).x
            cout = lambda a: float(np.sum((matrix @ a - rhs[:, column]) ** 2))  # noqa: E731
            pire = max(pire, cout(mine[:, column]) - cout(reference))

    # Notre solveur ne doit jamais faire moins bien que la référence.
    assert pire < 1e-4
