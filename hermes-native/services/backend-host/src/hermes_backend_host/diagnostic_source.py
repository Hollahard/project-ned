"""Copy only tracked Python source into a new diagnostic candidate; no execution."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

PIN = "649d6c0391029f35959cfbc240eb3534a6667cf5"
CONFIG_PIN = "d8118b064bb442e10ce6a90e8e23c7f347b6ff532781febab206d9c652f3c7dd"
WINDOWS_BEFORE = b'_IS_WINDOWS = platform.system() == "Windows"'
WINDOWS_AFTER = b'_IS_WINDOWS = sys.platform == "win32"'
PATCHES = {
    "hermes_cli/config.py": (CONFIG_PIN, WINDOWS_BEFORE, WINDOWS_AFTER),
    "hermes_state_dbfile.py": (
        "d1cd1b0fcf40375599e69fdcdcd3bb1257f659d0948ca168afa3747871130a9e",
        b'if platform.system() == "Windows":',
        b'if os.name == "nt":',
    ),
    "providers/__init__.py": (
        "3c5013938b0a8b186199d9a096b4e0c698b6bd12cf5623bc2ffa0673b5067645",
        b"def _run_discovery_steps() -> None:",
        b"def _run_discovery_steps() -> None:\n    return  # Managed diagnostic: provider discovery excluded.",
    ),
    "agent/secret_scope.py": (
        "5f2584dc93be49ef7e4de23f9f92a4abd05aa42aab8fc2fac40f54f9f8b9c664",
        b"def load_env_file(env_path: Path) -> Dict[str, str]:",
        b"def load_env_file(env_path: Path) -> Dict[str, str]:\n    return {}  # Managed diagnostic: environment-only credentials.",
    ),
}
PACKAGES = {
    "agent",
    "hermes_cli",
    "tools",
    "providers",
    "tui_gateway",
    "gateway",
    "pm",
    "plugins",
    "hermes_platform",
}


def build(source: Path, output: Path, git: Path) -> dict:
    source = source.resolve(strict=True)
    if output.resolve().is_relative_to(source) or source.is_relative_to(
        output.resolve()
    ):
        raise ValueError("Candidate and installed source must not overlap")
    if output.exists():
        raise ValueError("Candidate output must not exist")
    if not git.is_absolute() or not git.is_file():
        raise ValueError("An absolute Git executable is required")
    rev = subprocess.run(
        [str(git), "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if rev != PIN:
        raise ValueError("Unreviewed source revision")
    clean = subprocess.run(
        [str(git), "-C", str(source), "diff", "--quiet", "HEAD", "--", "*.py"],
        capture_output=True,
    )
    if clean.returncode != 0:
        raise ValueError("Tracked Python source differs from pinned commit")
    names = (
        subprocess.run(
            [str(git), "-C", str(source), "ls-files", "-z", "--", "*.py"],
            check=True,
            capture_output=True,
        )
        .stdout.decode()
        .split("\0")
    )
    records = {}
    pending = []
    edits = []
    for name in names:
        p = Path(name)
        if not name or (len(p.parts) > 1 and p.parts[0] not in PACKAGES):
            continue
        if "tests" in p.parts or p.name.startswith("test_"):
            continue
        original = source / p
        resolved = original.resolve(strict=True)
        if not resolved.is_relative_to(source) or original.is_symlink():
            raise ValueError("Source redirects outside checkout")
        data = original.read_bytes()
        if p.as_posix() in PATCHES:
            pin, before, after = PATCHES[p.as_posix()]
            if hashlib.sha256(data).hexdigest() != pin or data.count(before) != 1:
                raise ValueError("Unreviewed source at diagnostic patch")
            data = data.replace(before, after)
            edits.append(
                {
                    "path": p.as_posix(),
                    "original_sha256": pin,
                    "patched_sha256": hashlib.sha256(data).hexdigest(),
                    "before": before.decode(),
                    "after": after.decode(),
                }
            )
        records[p.as_posix()] = hashlib.sha256(data).hexdigest()
        pending.append((p, data))
    clean_after = subprocess.run(
        [str(git), "-C", str(source), "diff", "--quiet", "HEAD", "--", "*.py"],
        capture_output=True,
    )
    if clean_after.returncode != 0:
        raise ValueError("Tracked source changed while copying")
    output.mkdir(parents=True)
    for rel, data in pending:
        target = output / "source" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {
        "upstream_commit": rev,
        "mode": "diagnostic-http-subset-v1",
        "source_files": records,
        "upstream_edits": edits,
        "retained_handlers": [
            "hermes_cli.web_routers.config_env.get_config",
            "hermes_cli.web_routers.sessions.get_sessions",
        ],
        "excluded": [
            "stock startup and lifespan",
            "gateway RPC",
            "generation",
            "MCP",
            "plugins activation",
            "provider plugin/entrypoint discovery and provider catalog parity",
            "all dotenv credential sources",
            "updates",
            "rendezvous",
            "global reapers",
            "named profiles",
            "write routes",
        ],
    }
    (output / "source-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def verify(candidate: Path) -> dict:
    manifest = json.loads(
        (candidate / "source-manifest.json").read_text(encoding="utf-8")
    )
    if manifest.get("upstream_commit") != PIN:
        raise ValueError("Unreviewed manifest")
    root = (candidate / "source").resolve(strict=True)
    records = manifest["source_files"]
    expected_edits = [
        {
            "path": rel,
            "original_sha256": pin,
            "patched_sha256": records[rel],
            "before": before.decode(),
            "after": after.decode(),
        }
        for rel, (pin, before, after) in PATCHES.items()
    ]
    if sorted(manifest.get("upstream_edits", []), key=lambda x: x["path"]) != sorted(
        expected_edits, key=lambda x: x["path"]
    ):
        raise ValueError("Unreviewed source edits")
    if {p.relative_to(root).as_posix() for p in root.rglob("*.py")} != set(records):
        raise ValueError("Unexpected source file set")
    for rel, digest in records.items():
        path = root / rel
        if not path.resolve(strict=True).is_relative_to(root) or path.is_symlink():
            raise ValueError("Source path redirect")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Source hash mismatch")
        if rel in PATCHES:
            pin, before, after = PATCHES[rel]
            data = path.read_bytes()
            if (
                data.count(after) != 1
                or hashlib.sha256(data.replace(after, before)).hexdigest() != pin
            ):
                raise ValueError("Diagnostic patch is not the approved exact change")
    return manifest
