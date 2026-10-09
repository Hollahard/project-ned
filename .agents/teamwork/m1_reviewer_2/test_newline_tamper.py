import importlib.util
import shutil
from pathlib import Path
import pytest

PACKAGE = Path("hermes-native/services/owned-ws").resolve()

def test_crlf_to_lf_tamper(tmp_path):
    root = tmp_path / "owned-ws"
    root.mkdir()
    for source in PACKAGE.iterdir():
        if source.is_file():
            shutil.copyfile(source, root / source.name)
    shutil.copytree(PACKAGE / "vendor", root / "vendor")
    
    spec = importlib.util.spec_from_file_location("verifier", root / "verify_vendor.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    
    # 1. Base copy must pass
    assert verifier.verify() == 28, "Base copy must verify 28 files"
    
    # 2. Tamper CRLF file to LF in client.rs
    client_rs = root / "vendor/tungstenite/src/client.rs"
    raw = client_rs.read_bytes()
    assert b"\r\n" in raw, "client.rs must originally have CRLF"
    lf_raw = raw.replace(b"\r\n", b"\n")
    client_rs.write_bytes(lf_raw)
    
    # Must raise ValueError because hash changed
    try:
        verifier.verify()
        raise AssertionError("CRLF to LF tamper should have failed verification!")
    except ValueError as e:
        print(f"PASSED: CRLF to LF tamper correctly caught with ValueError: {e}")

if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        test_crlf_to_lf_tamper(Path(td))
    print("ALL NEWLINE TAMPER TESTS PASSED!")
