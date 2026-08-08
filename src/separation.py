"""Séparation : d'une image RVB vers N cartes de couverture d'encre.

Une carte de couverture vaut `1.0` là où l'encre est pleine, `0.0` là où le
papier reste nu — toujours dans ce sens, quelle que soit la convention de
sortie du profil. Voir doc/separation.md pour le modèle et les méthodes.
"""

from __future__ import annotations

import numpy as np

import itertools
from dataclasses import dataclass

from .color import LUMA_COEFFS, linear_to_srgb
from .config import Profile
from .errors import NotImplementedYet, ProfileError
from .image import luminance, relative_luminance
from .inks import density_matrix, luminance_density, to_density, transmittance

#: Couverture en deçà de laquelle `preserve_highlights` remet à zéro. Sous 2 %,
#: une trame ne dépose qu'un point isolé par cellule : il salit les blancs sans
#: apporter de nuance.
HIGHLIGHT_FLOOR = 0.02

#: Finesse des tables de courbes de réponse. Une courbe est linéaire par
#: morceaux : 8192 échantillons la restituent à mieux qu'un niveau 8 bits pour
#: toute pente raisonnable.
_CURVE_LUT_SIZE = 8192

_IMPLEMENTED = ("luminance", "duotone", "tritone", "cmyk", "density-lsq")

#: Primaires idéales visées par la méthode `cmyk`, en sRVB **encodé** — le
#: domaine où opère la séparation quadri, et où les distances discriminent le
#: mieux : un bon jeu riso s'y place à 0.26 de l'idéal, un jeu arbitraire à
#: 0.86, là où l'espace linéaire les rapprocherait à 0.37 contre 1.10.
#: Chaque encre du profil est affectée au rôle dont elle est la plus proche.
_CMYK_IDEALS = {
    "cyan": np.array([0.0, 1.0, 1.0], dtype=np.float32),
    "magenta": np.array([1.0, 0.0, 1.0], dtype=np.float32),
    "yellow": np.array([1.0, 1.0, 0.0], dtype=np.float32),
    "black": np.array([0.0, 0.0, 0.0], dtype=np.float32),
}

#: Distance moyenne à l'idéal au-delà de laquelle le jeu d'encres n'a plus
#: grand-chose de quadrichromique.
_CMYK_MISMATCH = 0.5

#: Pondération des canaux dans l'erreur de séparation. À mi-chemin entre un
#: traitement uniforme et la sensibilité de l'œil : une erreur dans le vert se
#: voit davantage qu'une erreur dans le bleu, mais pondérer strictement par la
#: luminance donnerait au bleu dix fois moins de poids qu'au vert et
#: dégraderait franchement les ciels.
_CHANNEL_WEIGHTS = np.sqrt(0.5 + 0.5 * 3.0 * LUMA_COEFFS).astype(np.float32)

#: Taille des blocs de pixels traités d'un coup par le solveur. Borne la
#: pointe mémoire indépendamment des dimensions de l'image.
_SOLVER_CHUNK = 2_000_000

#: Au-delà, l'énumération des jeux de contraintes (3^N) devient déraisonnable.
#: Un travail riso dépasse rarement quatre passages.
_MAX_INKS_LSQ = 5

#: Crête de stabilisation, en fraction de l'échelle des encres chromatiques.
#: Assez petite pour ne pas biaiser les couvertures, assez grande pour
#: départager les solutions quasi équivalentes.
_STABILISER = 0.02

_FREE, _AT_ZERO, _AT_CAP = 0, 1, 2


@dataclass(frozen=True)
class _ActiveSet:
    """Une répartition des encres entre libres, à zéro et au plafond.

    Tout y est précalculé et indépendant des pixels : c'est ce qui ramène la
    résolution à quelques produits matriciels par répartition.
    """

    free: tuple[int, ...]
    capped: tuple[int, ...]
    offset: np.ndarray | None  # (m,) contribution des encres au plafond
    pinv: np.ndarray | None  # (|F|, m) résolution des encres libres
    residual_form: np.ndarray  # (m, m) projecteur du résidu, symétrique
    free_caps: np.ndarray


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


def assign_cmyk_roles(profile: Profile) -> tuple[list[str], float]:
    """Affecte à chaque encre le rôle quadri dont elle est la plus proche.

    L'affectation est optimale : avec au plus quatre encres, on énumère les
    permutations plutôt que de choisir gloutonnement, ce qui éviterait mal les
    cas où deux encres se disputent le même rôle.
    """
    roles = ["cyan", "magenta", "yellow"]
    if len(profile.inks) == 4:
        roles.append("black")

    encoded = [linear_to_srgb(ink.color) for ink in profile.inks]

    best, best_cost = roles, float("inf")
    for candidate in itertools.permutations(roles):
        cost = sum(
            float(np.linalg.norm(color - _CMYK_IDEALS[role]))
            for color, role in zip(encoded, candidate)
        )
        if cost < best_cost:
            best, best_cost = list(candidate), cost

    return best, best_cost / len(profile.inks)


def _separate_cmyk(img: np.ndarray, profile: Profile) -> tuple[np.ndarray, list[str]]:
    """Séparation quadrichromique classique, pour un jeu d'encres proche du CMJN.

    Passage en CMJ, extraction du noir avec GCR paramétrable, puis mappage de
    chaque canal sur l'encre la plus proche. Sur des encres arbitraires, ce
    mappage devient une approximation grossière et `density-lsq` fait mieux —
    le programme le signale.

    La conversion opère dans le domaine perceptuel, comme toute séparation
    quadri classique : c'est là que `black_generation` se comporte comme on
    l'attend.
    """
    roles, mismatch = assign_cmyk_roles(profile)

    encoded = linear_to_srgb(img)
    channels = {
        "cyan": 1.0 - encoded[..., 0],
        "magenta": 1.0 - encoded[..., 1],
        "yellow": 1.0 - encoded[..., 2],
    }

    if "black" in roles:
        common = np.minimum(
            np.minimum(channels["cyan"], channels["magenta"]), channels["yellow"]
        )
        black = common * profile.separation.black_generation
        for name in ("cyan", "magenta", "yellow"):
            channels[name] = channels[name] - black
        channels["black"] = black

    coverage = np.stack([np.clip(channels[role], 0.0, 1.0) for role in roles])

    warnings: list[str] = []
    if mismatch > _CMYK_MISMATCH:
        pairs = ", ".join(
            f"{ink.label} → {role}" for ink, role in zip(profile.inks, roles)
        )
        warnings.append(
            f"`cmyk` sur un jeu d'encres éloigné de la quadrichromie ({pairs}). "
            "Le mappage est approximatif ; `density-lsq` gère ce cas nettement "
            "mieux."
        )

    return coverage.astype(np.float32), warnings


# --------------------------------------------------------------------------
# Séparation générale : moindres carrés bornés en espace densité


def build_system(profile: Profile) -> tuple[np.ndarray, np.ndarray]:
    """Matrice pondérée du système et plafonds, pour `density-lsq`.

    Le système est `M · a = D_cible − D_papier`, où la colonne `i` de `M` est
    la densité de l'encre `i`. Les lignes sont pondérées par canal.

    Avec quatre encres ou plus, il y a plus d'inconnues que d'équations :
    plusieurs combinaisons donnent la même couleur. `black_generation` ajoute
    alors une pénalité sur les encres claires, ce qui pousse le solveur à
    fabriquer les zones neutres avec l'encre la plus foncée — moins d'encre au
    total, meilleur séchage, repérage moins critique dans les ombres.
    """
    inks = profile.inks
    weighted = _CHANNEL_WEIGHTS[:, np.newaxis] * density_matrix(inks)
    caps = np.array([ink.max_coverage for ink in inks], dtype=np.float32)

    rows = [weighted]
    darkest = int(np.argmax(luminance_density(inks)))
    light = [i for i in range(len(inks)) if i != darkest] or [darkest]

    # Échelle de référence : les seules encres chromatiques. La moyenne de
    # toutes les colonnes serait dominée par l'encre foncée — un noir dense
    # pèse une dizaine de fois une encre chromatique — et toute pénalité
    # calée dessus étoufferait la couleur au lieu de l'arbitrer.
    scale = float(np.mean(np.sum(weighted[:, light] ** 2, axis=0)))

    # Stabilisateur permanent. Quand plusieurs combinaisons d'encres rendent
    # presque la même couleur, le choix bascule d'un pixel à l'autre et
    # l'image se mouchette. Une crête minime tranche ces quasi-ex æquo de
    # façon continue, sans peser sur les couvertures elles-mêmes.
    rows.append(np.eye(len(inks), dtype=np.float32) * np.sqrt(_STABILISER * scale))

    if len(inks) > 3 and profile.separation.black_generation > 0.0:
        penalty = np.zeros((len(light), len(inks)), dtype=np.float32)
        penalty[np.arange(len(light)), light] = np.sqrt(
            profile.separation.black_generation * scale
        )
        rows.append(penalty)

    return np.vstack(rows).astype(np.float32), caps


def build_active_sets(matrix: np.ndarray, caps: np.ndarray) -> list[_ActiveSet]:
    """Précalcule les 3^N répartitions. Ne dépend que du profil, jamais des pixels.

    `residual_form` est `I − P`, où `P` projette orthogonalement sur l'espace
    engendré par les encres libres. Le résidu d'un pixel vaut alors la forme
    quadratique `tᵀ(I − P)t`, ce qui évite de reconstruire la solution complète
    pour chaque répartition simplement afin de la comparer aux autres.
    """
    count = matrix.shape[1]
    rows = matrix.shape[0]
    identity = np.eye(rows, dtype=np.float32)
    sets: list[_ActiveSet] = []

    for pattern in itertools.product((_FREE, _AT_ZERO, _AT_CAP), repeat=count):
        free = tuple(i for i, state in enumerate(pattern) if state == _FREE)
        capped = tuple(i for i, state in enumerate(pattern) if state == _AT_CAP)

        if free:
            columns = matrix[:, free]
            pinv = np.linalg.pinv(columns).astype(np.float32)
            residual_form = identity - columns @ pinv
        else:
            pinv = None
            residual_form = identity

        sets.append(
            _ActiveSet(
                free=free,
                capped=capped,
                offset=(
                    (matrix[:, capped] @ caps[list(capped)]).astype(np.float32)
                    if capped
                    else None
                ),
                pinv=pinv,
                residual_form=residual_form.astype(np.float32),
                free_caps=caps[list(free)],
            )
        )

    return sets


def solve_bounded_lsq(
    matrix: np.ndarray,
    rhs: np.ndarray,
    caps: np.ndarray,
    tol: float = 1e-5,
    active_sets: list[_ActiveSet] | None = None,
) -> np.ndarray:
    """Moindres carrés bornés `min ‖A·a − b‖²` sous `0 ≤ a ≤ caps`, vectorisé.

    `rhs` est `(m, P)` : une colonne par pixel. Le résultat est `(N, P)`.

    L'optimum d'un problème borné est atteint en fixant un sous-ensemble des
    variables à leurs bornes et en résolvant librement le reste. Comme `N` est
    petit, on énumère les 3^N répartitions possibles : chacune se ramène à une
    application linéaire constante, donc à un produit matriciel sur tous les
    pixels d'un coup. Parmi les candidats **réalisables**, celui de plus petit
    résidu est l'optimum exact — un candidat réalisable est un point admissible
    du problème d'origine, son coût majore donc l'optimum.

    C'est ce qui permet de rester vectorisé. Un solveur généraliste comme
    `scipy.optimize.lsq_linear` traite un problème à la fois : sur les 37 Mpx
    d'un A4 à 600 dpi, il faudrait des heures. Les tests s'en servent en
    revanche comme référence indépendante.
    """
    sets = build_active_sets(matrix, caps) if active_sets is None else active_sets

    # `itertools.product` place `_FREE` en premier : la répartition 0 est celle
    # où toutes les encres sont libres, donc la solution non contrainte. Elle
    # suffit pour la plupart des pixels d'une photo — on ne paie l'énumération
    # que sur les autres.
    guess = (sets[0].pinv @ rhs).astype(np.float32)
    inside = np.all((guess >= -tol) & (guess <= caps[:, np.newaxis] + tol), axis=0)

    out = np.clip(guess, 0.0, caps[:, np.newaxis])
    if inside.all():
        return out

    outside = np.flatnonzero(~inside)
    out[:, outside] = _best_active_set(
        sets, np.ascontiguousarray(rhs[:, outside]), caps, tol
    )
    return out


def _best_active_set(
    sets: list[_ActiveSet], rhs: np.ndarray, caps: np.ndarray, tol: float
) -> np.ndarray:
    """Retient, pour chaque pixel, la répartition réalisable de moindre résidu.

    Deux passes. La première ne calcule que ce qui sert à départager — le
    résidu et la réalisabilité — sans jamais matérialiser la solution complète
    d'une répartition perdante. La seconde ne reconstruit que les gagnantes, ce
    qui revient au coût d'une seule répartition étalée sur toute l'image.
    """
    pixels = rhs.shape[1]
    count = caps.shape[0]

    best_residual = np.full(pixels, np.inf, dtype=np.float32)
    best_index = np.zeros(pixels, dtype=np.int16)

    for index, active in enumerate(sets):
        target = rhs if active.offset is None else rhs - active.offset[:, np.newaxis]

        if active.free:
            solved = active.pinv @ target
            usable = np.all(
                (solved >= -tol) & (solved <= active.free_caps[:, np.newaxis] + tol),
                axis=0,
            )
            if not usable.any():
                continue
        else:
            usable = None

        residual = np.einsum("ip,ip->p", active.residual_form @ target, target)

        better = residual < best_residual
        if usable is not None:
            better &= usable
        best_residual = np.where(better, residual, best_residual)
        best_index[better] = index

    out = np.zeros((count, pixels), dtype=np.float32)
    for index, active in enumerate(sets):
        chosen = np.flatnonzero(best_index == index)
        if chosen.size == 0:
            continue

        block = np.zeros((count, chosen.size), dtype=np.float32)
        if active.capped:
            block[list(active.capped)] = caps[list(active.capped)][:, np.newaxis]
        if active.free:
            target = rhs[:, chosen]
            if active.offset is not None:
                target = target - active.offset[:, np.newaxis]
            block[list(active.free)] = active.pinv @ target
        out[:, chosen] = block

    return np.clip(out, 0.0, caps[:, np.newaxis])


def _separate_density_lsq(img: np.ndarray, profile: Profile) -> np.ndarray:
    """Séparation générale : n'importe quel jeu d'encres.

    Le traitement se fait par blocs de lignes : sur un A4 à 600 dpi, matérialiser
    d'un coup les densités cibles et tous les candidats du solveur dépasserait
    plusieurs gigaoctets.
    """
    if len(profile.inks) > _MAX_INKS_LSQ:
        raise ProfileError(
            f"`density-lsq` gère jusqu'à {_MAX_INKS_LSQ} encres, le profil en "
            f"déclare {len(profile.inks)}."
        )

    matrix, caps = build_system(profile)
    active_sets = build_active_sets(matrix, caps)  # une fois, pas par bloc
    paper_density = to_density(profile.paper.color) * _CHANNEL_WEIGHTS

    # Densité maximale que le jeu d'encres sait produire, canal par canal.
    # Au-delà, la cible est hors d'atteinte : la réclamer quand même fait
    # courir le solveur après l'impossible et lui fait sacrifier les canaux
    # qu'il aurait pu servir. Un rouge saturé demande une densité infinie en
    # vert et en bleu — ramenée à 4.0 par le plancher, soit trois fois le
    # maximum atteignable — et ressortait en gris-bleu parce que le solveur
    # saturait l'encre bleue pour gratter ce résidu, tuant le rouge au passage.
    reachable = (matrix[:3] @ caps)[:, np.newaxis]

    height, width = img.shape[:2]
    out = np.empty((len(profile.inks), height, width), dtype=np.float32)
    rows = max(1, _SOLVER_CHUNK // width)

    for start in range(0, height, rows):
        stop = min(height, start + rows)
        block = to_density(img[start:stop]) * _CHANNEL_WEIGHTS
        block -= paper_density

        rhs = np.ascontiguousarray(block.reshape(-1, 3).T)
        np.minimum(rhs, reachable, out=rhs)

        padding = matrix.shape[0] - 3
        if padding:
            rhs = np.vstack([rhs, np.zeros((padding, rhs.shape[1]), dtype=np.float32)])

        solved = solve_bounded_lsq(matrix, rhs, caps, active_sets=active_sets)
        out[:, start:stop] = solved.reshape(-1, stop - start, width)

    return out


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
        # Défensif : la validation du profil rejette déjà toute méthode
        # inconnue. Ce garde-fou n'attrape qu'un oubli de câblage.
        raise NotImplementedYet(
            f"La séparation {method!r} n'est pas câblée.\n"
            f"Méthodes disponibles : {', '.join(_IMPLEMENTED)}."
        )

    warnings: list[str] = []
    if method == "luminance":
        coverage = _separate_luminance(img, profile)
    elif method == "density-lsq":
        coverage = _separate_density_lsq(img, profile)
    elif method == "cmyk":
        coverage, warnings = _separate_cmyk(img, profile)
    else:
        coverage = _separate_tonal(img, profile)

    if profile.separation.preserve_highlights:
        coverage = np.where(coverage < HIGHLIGHT_FLOOR, 0.0, coverage)

    coverage, stats = limit_ink(coverage, profile)
    stats["warnings"] = warnings
    return coverage, stats
