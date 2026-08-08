"""La CLI doit toujours retourner un code, jamais laisser remonter une trace."""

from __future__ import annotations

import json

import numpy as np
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


def test_run_complet(workspace, monkeypatch, capsys):
    assert run(["demo", "-c", "test"], workspace, monkeypatch) == 0

    produced = {p.name for p in (workspace / "project" / "demo" / "output").iterdir()}
    assert produced == {
        "01_pink.png",
        "02_black.png",
        "preview.png",
        "todo.md",
        "run.json",
    }

    out = capsys.readouterr().out
    assert "Couvertures :" in out
    assert "Encrage total" in out


def test_second_run_ecrase_le_premier(workspace, monkeypatch):
    """La signature `run.json` autorise l'écrasement sans question."""
    output = workspace / "project" / "demo" / "output"

    run(["demo", "-c", "test"], workspace, monkeypatch)
    (output / "trace.txt").write_text("reliquat", encoding="utf-8")

    assert run(["demo", "-c", "test"], workspace, monkeypatch) == 0
    assert not (output / "trace.txt").exists()


def test_run_refuse_decraser_un_dossier_etranger(workspace, monkeypatch, capsys):
    output = workspace / "project" / "demo" / "output"
    output.mkdir()
    (output / "retouche.psd").write_bytes(b"")

    assert run(["demo", "-c", "test"], workspace, monkeypatch) == 1
    assert (output / "retouche.psd").exists()
    assert "run.json" in capsys.readouterr().err


def test_preview_only_ne_produit_pas_les_calques(workspace, monkeypatch):
    assert run(["demo", "-c", "test", "--preview-only"], workspace, monkeypatch) == 0

    produced = {p.name for p in (workspace / "project" / "demo" / "output").iterdir()}
    assert produced == {"preview.png", "run.json"}


def test_run_json_reproduit_le_profil(workspace, monkeypatch):
    run(["demo", "-c", "test", "--dpi", "150"], workspace, monkeypatch)

    payload = json.loads(
        (workspace / "project" / "demo" / "output" / "run.json").read_text(encoding="utf-8")
    )
    assert payload["project"] == "demo"
    assert payload["profile"]["output"]["dpi"] == 150
    assert payload["profile"]["inks"][0]["color"] == "#FF48B0"
    assert [layer["file"] for layer in payload["layers"]] == ["01_pink.png", "02_black.png"]
    assert payload["total_ink_max"] <= 1.7 + 1e-6


def test_les_calques_sortent_trames(workspace, monkeypatch):
    """Le profil de test demande `clustered-dot` : les fichiers doivent l'être."""
    from PIL import Image

    run(["demo", "-c", "test"], workspace, monkeypatch)

    calque = np.asarray(
        Image.open(workspace / "project" / "demo" / "output" / "01_pink.png")
    )
    assert set(np.unique(calque)) <= {0, 255}


def test_no_halftone_produit_du_ton_continu(workspace, monkeypatch):
    from PIL import Image

    run(["demo", "-c", "test", "--no-halftone"], workspace, monkeypatch)

    calque = np.asarray(
        Image.open(workspace / "project" / "demo" / "output" / "01_pink.png")
    )
    assert len(np.unique(calque)) > 2


def test_le_plan_decrit_la_trame_appliquee(workspace, monkeypatch):
    run(["demo", "-c", "test"], workspace, monkeypatch)
    plan = (workspace / "project" / "demo" / "output" / "todo.md").read_text(
        encoding="utf-8"
    )
    assert "points agglomérés" in plan
    assert "ton continu" not in plan


def test_preview_halftoned(workspace, monkeypatch):
    """L'aperçu tramé montre le grain, donc plus de détail que le continu."""
    from PIL import Image

    output = workspace / "project" / "demo" / "output"

    run(["demo", "-c", "test", "--dpi", "600"], workspace, monkeypatch)
    continu = np.asarray(Image.open(output / "preview.png")).astype(np.int16)

    run(["demo", "-c", "test", "--dpi", "600", "--preview-halftoned"], workspace, monkeypatch)
    trame = np.asarray(Image.open(output / "preview.png")).astype(np.int16)

    assert trame.shape == continu.shape
    assert float(np.abs(np.diff(trame, axis=1)).mean()) > float(
        np.abs(np.diff(continu, axis=1)).mean()
    )


def test_out_redirige_la_sortie(workspace, monkeypatch):
    assert run(["demo", "-c", "test", "--out", "ailleurs"], workspace, monkeypatch) == 0

    produced = {p.name for p in (workspace / "ailleurs").iterdir()}
    assert "01_pink.png" in produced and "run.json" in produced
    assert not (workspace / "project" / "demo" / "output").exists()


def test_out_refuse_un_dossier_contenant_le_projet(workspace, monkeypatch, capsys):
    """`--out project` effacerait la photo source."""
    assert run(["demo", "-c", "test", "--out", "project"], workspace, monkeypatch) == 1
    assert "contient le projet" in capsys.readouterr().err
    assert (workspace / "project" / "demo" / "source.jpg").exists()


def test_out_refuse_la_racine(workspace, monkeypatch, capsys):
    assert run(["demo", "-c", "test", "--out", "/"], workspace, monkeypatch) == 1
    assert "racine du système" in capsys.readouterr().err


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
