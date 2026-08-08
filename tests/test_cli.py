"""La CLI doit toujours retourner un code, jamais laisser remonter une trace."""

from __future__ import annotations

import json

import pytest

from src.cli import build_parser, cli_overrides, main


def run(argv, workspace, monkeypatch):
    monkeypatch.chdir(workspace)
    return main(argv)


def test_dry_run_reussit(workspace, monkeypatch, capsys):
    assert run(["demo", "-c", "test", "--dry-run"], workspace, monkeypatch) == 0
    out = capsys.readouterr().out
    assert "Projet     : demo" in out
    assert "Fluorescent" not in out
    assert "1. pink" in out


def test_projet_introuvable(workspace, monkeypatch, capsys):
    assert run(["absent", "-c", "test", "--dry-run"], workspace, monkeypatch) == 1
    assert "Projet introuvable" in capsys.readouterr().err


def test_profil_introuvable(workspace, monkeypatch, capsys):
    assert run(["demo", "-c", "absent", "--dry-run"], workspace, monkeypatch) == 1
    assert "Profil introuvable" in capsys.readouterr().err


def test_profil_invalide(workspace, monkeypatch, capsys):
    (workspace / "config" / "casse.json").write_text(
        json.dumps({"inks": [{"name": "x"}]}), encoding="utf-8"
    )
    assert run(["demo", "-c", "casse", "--dry-run"], workspace, monkeypatch) == 2
    err = capsys.readouterr().err
    assert "Profil invalide" in err
    assert "color" in err


def test_ecriture_pas_encore_ecrite(workspace, monkeypatch, capsys):
    """Un lot non terminé s'arrête sur un message explicite, pas un plantage."""
    assert run(["demo", "-c", "test"], workspace, monkeypatch) == 3

    captured = capsys.readouterr()
    assert "pas encore là" in captured.err
    # La séparation, elle, a bien abouti.
    assert "Couvertures :" in captured.out
    assert "Encrage total" in captured.out


def test_surcharge_dpi_visible_dans_le_resume(workspace, monkeypatch, capsys):
    assert (
        run(["demo", "-c", "test", "--dpi", "1200", "--dry-run"], workspace, monkeypatch)
        == 0
    )
    assert "1200 dpi" in capsys.readouterr().out


def test_no_halftone_desactive_la_trame(workspace, monkeypatch, capsys):
    run(["demo", "-c", "test", "--no-halftone", "--dry-run"], workspace, monkeypatch)
    assert "ton continu" in capsys.readouterr().out


def test_avertissements_affiches(workspace, monkeypatch, capsys):
    run(["demo", "-c", "test", "--dpi", "300", "--dry-run"], workspace, monkeypatch)
    assert "Avertissements" in capsys.readouterr().out


def test_verbose_trace_lorigine_du_profil(workspace, monkeypatch, capsys):
    run(["demo", "-c", "test", "--dry-run", "-v"], workspace, monkeypatch)
    assert "Profil issu de" in capsys.readouterr().out


def test_surcharges_traduites():
    args = build_parser().parse_args(["demo", "-c", "test", "--dpi", "600"])
    assert cli_overrides(args) == {"output": {"dpi": 600}}

    args = build_parser().parse_args(["demo", "-c", "test"])
    assert cli_overrides(args) == {}


def test_config_obligatoire():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["demo"])
