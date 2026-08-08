"""Chargement de l'image source, géométrie et corrections tonales.

Ce module ne connaît pas les encres : il produit une image RVB linéaire propre,
à la bonne taille, corrigée en tons — ce que la séparation attend en entrée.

Deux conventions structurantes, détaillées dans doc/architecture.md :

- l'image est en `float32` linéaire dans [0, 1] dès le chargement, parce que
  tout mélange de couleur effectué en gamma est faux ;
- les **corrections tonales**, elles, sont appliquées dans le domaine
  perceptuel. Un contraste ou un gamma calculés en linéaire pivoteraient
  autour d'une valeur qui n'est pas le gris moyen et donneraient un résultat
  contre-intuitif. `apply_tone` fait l'aller-retour en interne : son entrée et
  sa sortie restent linéaires.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .color import LUMA_COEFFS, linear_to_srgb, srgb_to_linear
from .config import ToneCfg
from .errors import RisoError

MM_PER_INCH = 25.4

#: Orientations EXIF qui échangent largeur et hauteur.
_EXIF_ORIENTATION_TAG = 274
_EXIF_TRANSPOSED = (5, 6, 7, 8)

_LANCZOS = getattr(Image, "Resampling", Image).LANCZOS

#: Une image 8 bits n'a que 256 valeurs possibles par canal : la conversion
#: vers le linéaire se fait par table plutôt que par `np.power` sur 100 M de
#: pixels.
_SRGB8_TO_LINEAR = srgb_to_linear(np.arange(256, dtype=np.float32) / 255.0)

#: Finesse de la table des corrections tonales. 8192 échantillons en domaine
#: linéaire tiennent l'erreur sous un demi-niveau 8 bits, y compris dans les
#: basses lumières où l'échelle linéaire est la moins favorable.
_TONE_LUT_SIZE = 8192


# --------------------------------------------------------------------------
# Chargement


def _to_srgb(img: Image.Image) -> Image.Image:
    """Convertit vers sRVB via le profil ICC embarqué, s'il y en a un.

    Sans profil — le cas courant d'un JPEG d'appareil photo — l'image est
    supposée sRVB. Un échec de conversion n'interrompt pas le run : mieux vaut
    une colorimétrie approchée qu'un arrêt sur une photo par ailleurs valide.
    """
    icc = img.info.get("icc_profile")
    if not icc:
        return img

    try:
        import io

        from PIL import ImageCms

        source = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        return ImageCms.profileToProfile(
            img, source, ImageCms.createProfile("sRGB"), outputMode="RGB"
        )
    except Exception:  # ICC exotique, ImageCms absent : on suppose sRVB
        return img


def _flatten_alpha(img: Image.Image) -> Image.Image:
    """Aplatit la transparence sur du blanc.

    Une zone transparente n'a pas de sens à l'impression : elle correspond au
    papier nu, donc à une absence d'encre.
    """
    if img.mode not in ("RGBA", "LA", "PA", "P"):
        return img
    img = img.convert("RGBA")
    background = Image.new("RGBA", img.size, (255, 255, 255, 255))
    return Image.alpha_composite(background, img)


def load_linear(path: Path) -> np.ndarray:
    """Charge une image et la rend en RVB linéaire `(H, W, 3)` float32.

    L'orientation EXIF est appliquée : sans cela, une photo prise en portrait
    ressortirait couchée.
    """
    try:
        img = Image.open(path)
        img.load()
    except OSError as exc:
        raise RisoError(f"{path} : image illisible — {exc}") from exc

    img = ImageOps.exif_transpose(img)
    img = _to_srgb(img)
    img = _flatten_alpha(img)
    img = img.convert("RGB")

    return _SRGB8_TO_LINEAR[np.asarray(img, dtype=np.uint8)]


def source_size(path: Path) -> tuple[int, int]:
    """Dimensions `(largeur, hauteur)` sans décoder les pixels.

    PIL lit l'en-tête paresseusement ; l'orientation EXIF est prise en compte
    car elle peut échanger les deux dimensions.
    """
    try:
        with Image.open(path) as img:
            width, height = img.size
            orientation = img.getexif().get(_EXIF_ORIENTATION_TAG)
    except OSError as exc:
        raise RisoError(f"{path} : image illisible — {exc}") from exc

    if orientation in _EXIF_TRANSPOSED:
        return height, width
    return width, height


# --------------------------------------------------------------------------
# Géométrie


def target_long_edge_px(long_edge_mm: float, dpi: int) -> int:
    """Longueur du grand côté en pixels, pour un format en mm et une résolution."""
    return max(1, round(long_edge_mm / MM_PER_INCH * dpi))


def resize_to(img: np.ndarray, long_edge_px: int) -> np.ndarray:
    """Redimensionne en préservant le ratio : le grand côté vaut `long_edge_px`.

    Le rééchantillonnage a lieu en **espace linéaire**, ce qui est la seule
    façon correcte de moyenner des pixels. Lanczos peut produire un léger
    dépassement des bornes sur les contrastes francs : on réécrête.
    """
    height, width = img.shape[:2]
    if max(height, width) == long_edge_px:
        return img

    scale = long_edge_px / max(height, width)
    target = (max(1, round(width * scale)), max(1, round(height * scale)))

    channels = [
        np.asarray(
            Image.fromarray(img[:, :, c], mode="F").resize(target, _LANCZOS),
            dtype=np.float32,
        )
        for c in range(img.shape[2])
    ]
    return np.clip(np.stack(channels, axis=-1), 0.0, 1.0)


def resolution_warning(source_px: int, target_px: int) -> str | None:
    """Signale une source trop petite pour la sortie demandée.

    Le programme agrandit quand même, mais le dit : un calque interpolé vers le
    haut puis tramé produit une bouillie de points que l'aperçu ne montre pas
    toujours.
    """
    if source_px >= target_px:
        return None
    return (
        f"sous-résolution : la source fait {source_px} px au grand côté pour "
        f"{target_px} px demandés ({target_px / source_px:.1f}× d'agrandissement). "
        "Le détail sera interpolé, et le tramage le rendra visible."
    )


# --------------------------------------------------------------------------
# Luminance


def relative_luminance(img: np.ndarray) -> np.ndarray:
    """Luminance Y en lumière linéaire (Rec. 709)."""
    return np.tensordot(img, LUMA_COEFFS, axes=([-1], [0])).astype(np.float32)


def luminance(img: np.ndarray) -> np.ndarray:
    """Luminance sur une échelle perceptuelle, `(H, W)` dans [0, 1].

    C'est cette échelle que prennent en entrée les courbes de réponse des
    séparations `duotone` et `tritone` : un gris moyen y vaut ~0.5, ce qui rend
    les points de contrôle lisibles. La version linéaire, où le gris moyen vaut
    0.216, est disponible via `relative_luminance`.
    """
    return linear_to_srgb(relative_luminance(img))


# --------------------------------------------------------------------------
# Corrections tonales


def _s_curve(x: np.ndarray, amount: float) -> np.ndarray:
    """Courbe en S d'intensité `amount` ∈ [-1, 1], pivotant sur le gris moyen.

    Positif : mélange vers un `smoothstep`, qui creuse les extrémités et
    redresse les tons moyens. Négatif : mélange vers sa réciproque exacte, qui
    aplatit le contraste. Les deux fixent 0, 0.5 et 1, et restent monotones.
    """
    if amount > 0:
        target = x * x * (3.0 - 2.0 * x)
    else:
        target = 0.5 - np.sin(np.arcsin(np.clip(1.0 - 2.0 * x, -1.0, 1.0)) / 3.0)
    weight = abs(amount)
    return ((1.0 - weight) * x + weight * target).astype(np.float32)


def tone_curve(x: np.ndarray, cfg: ToneCfg) -> np.ndarray:
    """Courbe tonale scalaire, linéaire → linéaire.

    Définition de référence, appliquée telle quelle aux 8192 échantillons de la
    table. Niveaux, gamma et contraste opèrent dans le domaine perceptuel : en
    linéaire, ils pivoteraient autour d'une valeur qui n'est pas le gris moyen.
    """
    y = linear_to_srgb(x)

    if cfg.black_point != 0.0 or cfg.white_point != 1.0:
        y = np.clip((y - cfg.black_point) / (cfg.white_point - cfg.black_point), 0.0, 1.0)

    if cfg.gamma != 1.0:
        y = np.power(np.clip(y, 0.0, 1.0), 1.0 / cfg.gamma)

    if cfg.contrast != 0.0:
        y = _s_curve(np.clip(y, 0.0, 1.0), cfg.contrast)

    return srgb_to_linear(np.clip(y, 0.0, 1.0))


def apply_tone(img: np.ndarray, cfg: ToneCfg) -> np.ndarray:
    """Applique les corrections tonales du profil. Linéaire en entrée et sortie.

    La désaturation vient d'abord, en linéaire : c'est un mélange de lumière.
    Le reste est une fonction scalaire identique sur les trois canaux, donc
    tabulée une fois puis appliquée par indexation — sur les ~37 Mpx d'un A4 à
    600 dpi, cela ramène l'étape de plusieurs secondes à une fraction de
    seconde. C'est ce qui rend `--preview-only` utilisable pour itérer.
    """
    if cfg.is_identity:
        return img

    out = img
    if cfg.desaturate > 0.0:
        gray = relative_luminance(out)[..., np.newaxis]
        out = (1.0 - cfg.desaturate) * out + cfg.desaturate * gray

    lut = tone_curve(np.linspace(0.0, 1.0, _TONE_LUT_SIZE, dtype=np.float32), cfg)
    index = np.rint(np.clip(out, 0.0, 1.0) * (_TONE_LUT_SIZE - 1)).astype(np.int32)
    return lut[index]
