import json
import sys

import prepare_assets
import pytest


def baseline(source):
    source.mkdir()
    (source / "index.html").write_text("synthetic fixture HTML")
    (source / "feasibility-report.json").write_text(
        json.dumps(
            {
                "revision": prepare_assets.PIN,
                "sourceSha256": prepare_assets.SOURCE_HASH,
                "upstreamInputsUnchanged": True,
            }
        )
    )


def test_packaging_copies_inputs_and_refuses_existing_output(tmp_path, monkeypatch):
    source, output = tmp_path / "source", tmp_path / "output"
    baseline(source)
    monkeypatch.setattr(
        sys,
        "argv",
        ["prepare", "--renderer-dist", str(source), "--output", str(output)],
    )
    prepare_assets.main()
    assert (source / "index.html").read_bytes() == (output / "index.html").read_bytes()
    receipt = json.loads((output / "native-asset-receipt.json").read_text())
    assert "binding-proof.js" in receipt["asset_sha256"]
    assert receipt["visual_parity_verified"] is False
    with pytest.raises(ValueError, match="new directory"):
        prepare_assets.main()


def test_changed_baseline_rejects_before_creating_output(tmp_path, monkeypatch):
    source, output = tmp_path / "source", tmp_path / "output"
    baseline(source)
    (source / "feasibility-report.json").write_text(
        json.dumps({"revision": "unreviewed"})
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["prepare", "--renderer-dist", str(source), "--output", str(output)],
    )
    with pytest.raises(ValueError, match="baseline differs"):
        prepare_assets.main()
    assert not output.exists()
