from __future__ import annotations

import pytest

from src.errors import UsageError
from src.project import find_source, prepare_output, resolve_project


def test_resolution_nominale(workspace):
    project = resolve_project("demo", base=workspace / "project")
    assert project.name == "demo"
    assert project.source.name == "source.jpg"
    assert project.output_dir.name == "output"


def test_projet_introuvable_liste_les_disponibles(workspace):
    with pytest.raises(UsageError) as excinfo:
        resolve_project("absent", base=workspace / "project")
    assert "demo" in str(excinfo.value)
    assert excinfo.value.code == 1


def test_projet_absent_sans_dossier_project(tmp_path):
    with pytest.raises(UsageError):
        resolve_project("demo", base=tmp_path / "project")


# --------------------------------------------------------------------------
# Détection de la source


def test_image_unique(tmp_path):
    (tmp_path / "photo.png").write_bytes(b"")
    assert find_source(tmp_path).name == "photo.png"


def test_aucune_image(tmp_path):
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    with pytest.raises(UsageError, match="Aucune image"):
        find_source(tmp_path)


def test_plusieurs_images_source_lemporte(tmp_path):
    (tmp_path / "essai.png").write_bytes(b"")
    (tmp_path / "source.jpg").write_bytes(b"")
    assert find_source(tmp_path).name == "source.jpg"


def test_plusieurs_images_sans_source_est_ambigu(tmp_path):
    (tmp_path / "a.png").write_bytes(b"")
    (tmp_path / "b.jpg").write_bytes(b"")
    with pytest.raises(UsageError, match="Plusieurs images"):
        find_source(tmp_path)


def test_extension_insensible_a_la_casse(tmp_path):
    (tmp_path / "photo.JPG").write_bytes(b"")
    assert find_source(tmp_path).name == "photo.JPG"


def test_les_sous_dossiers_sont_ignores(tmp_path):
    (tmp_path / "source.jpg").write_bytes(b"")
    sub = tmp_path / "output"
    sub.mkdir()
    (sub / "01_black.png").write_bytes(b"")
    assert find_source(tmp_path).name == "source.jpg"


# --------------------------------------------------------------------------
# Préparation du dossier de sortie


def test_creation_si_absent(workspace):
    project = resolve_project("demo", base=workspace / "project")
    assert prepare_output(project).is_dir()


def test_ecrasement_dun_run_precedent(workspace):
    project = resolve_project("demo", base=workspace / "project")
    project.output_dir.mkdir()
    (project.output_dir / "run.json").write_text("{}", encoding="utf-8")
    (project.output_dir / "01_black.png").write_bytes(b"")

    prepare_output(project)

    assert project.output_dir.is_dir()
    assert list(project.output_dir.iterdir()) == []


def test_refus_decraser_un_dossier_non_produit_par_le_programme(workspace):
    project = resolve_project("demo", base=workspace / "project")
    project.output_dir.mkdir()
    precieux = project.output_dir / "retouche-manuelle.psd"
    precieux.write_bytes(b"")

    with pytest.raises(UsageError, match="run.json"):
        prepare_output(project)

    assert precieux.exists()


def test_dossier_vide_sans_signature_est_acceptable(workspace):
    project = resolve_project("demo", base=workspace / "project")
    project.output_dir.mkdir()
    assert prepare_output(project).is_dir()


def test_la_source_survit_a_la_preparation(workspace):
    project = resolve_project("demo", base=workspace / "project")
    prepare_output(project)
    assert project.source.exists()
