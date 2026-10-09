"""Reject tampering with the exact protocol source inventory and patch receipt."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]


@pytest.fixture
def vendor_copy(tmp_path):
    root = tmp_path / "owned-ws"
    root.mkdir()
    for source in PACKAGE.iterdir():
        if source.is_file():
            shutil.copyfile(source, root / source.name)
    shutil.copytree(PACKAGE / "vendor", root / "vendor")
    spec = importlib.util.spec_from_file_location(
        "isolated_vendor_verifier", root / "verify_vendor.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return root, module


def read_receipt(root):
    return json.loads((root / "vendor-patch-receipt.json").read_text("utf-8"))


def write_receipt(root, receipt):
    (root / "vendor-patch-receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", "utf-8"
    )


def test_exact_vendor_inventory_passes(vendor_copy):
    root, verifier = vendor_copy
    assert verifier.verify() == len(read_receipt(root)["files"])


def test_modified_protocol_bytes_fail(vendor_copy):
    root, verifier = vendor_copy
    target = root / "vendor/tungstenite/src/protocol/mod.rs"
    target.write_bytes(target.read_bytes() + b"\n// unexpected protocol edit\n")
    with pytest.raises(ValueError):
        verifier.verify()


def test_extra_unlisted_file_fails(vendor_copy):
    root, verifier = vendor_copy
    (root / "vendor/tungstenite/src/unlisted.rs").write_bytes(b"pub fn extra() {}\n")
    with pytest.raises(ValueError):
        verifier.verify()


def test_missing_file_fails(vendor_copy):
    root, verifier = vendor_copy
    (root / "vendor/tungstenite/src/protocol/mod.rs").unlink()
    with pytest.raises(ValueError):
        verifier.verify()


def test_wrong_revision_fails(vendor_copy):
    root, verifier = vendor_copy
    receipt = read_receipt(root)
    receipt["pack_revision"] = "unreviewed-revision"
    write_receipt(root, receipt)
    with pytest.raises(ValueError):
        verifier.verify()


def test_receipt_cannot_name_parent_path(vendor_copy):
    root, verifier = vendor_copy
    receipt = read_receipt(root)
    receipt["files"][0]["path"] = "../outside.rs"
    write_receipt(root, receipt)
    with pytest.raises(ValueError):
        verifier.verify()


def test_receipt_cannot_omit_changed_file_patch(vendor_copy):
    root, verifier = vendor_copy
    receipt = read_receipt(root)
    receipt["patches"] = receipt["patches"][1:]
    write_receipt(root, receipt)
    with pytest.raises(ValueError):
        verifier.verify()


def test_wrong_upstream_preimage_fails(vendor_copy, tmp_path):
    root, verifier = vendor_copy
    upstream = tmp_path / "upstream"
    shutil.copytree(root / "vendor/tungstenite", upstream)
    # The patched output is deliberately not an official upstream preimage.
    with pytest.raises(ValueError):
        verifier.verify(upstream)
