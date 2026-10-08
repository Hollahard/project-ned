# Retained-handler diagnostic subset

This opt-in host mounts unchanged upstream GET configuration and session-list handlers in a fresh synthetic home. It rejects every other route/method and profile override before dispatch. It does not start stock Hermes, chat, gateway RPC, inference, plugins or global startup services. See the [live checkpoint](../../../../docs/hermes-native-desktop/LIVE-RUNTIME-CHECKPOINT.md) and recorded source patch manifest.

Activate the main venv, then run from the backend-host package. Use an absolute Git executable and new candidate/state directories:

```powershell
$env:PYTHONPATH = (Resolve-Path ./src).Path
python -c "from pathlib import Path; from hermes_backend_host.diagnostic_source import build; build(Path(r'G:\Personal_Assistant\hermes\hermes-agent'), Path(r'.checks\candidate-new'), Path(r'C:\Program Files\Git\cmd\git.exe'))"
python ./diagnostics/run_proof.py --candidate ./.checks/candidate-new --interpreter 'G:\Personal_Assistant\hermes\hermes-agent\venv\Scripts\python.exe' --site-packages 'G:\Personal_Assistant\hermes\hermes-agent\venv\Lib\site-packages' --state ./.checks/state-new
python -m pytest -q --basetemp=.checks/new-test-run
python -m ruff check src diagnostics tests
python -m ruff format --check src diagnostics tests
```

The source builder rejects revision/hash drift, copied-source edits and redirects. The serving process belongs to a private owned Job before execution; each established HTTP connection is checked against that Job before headers carry the ephemeral token. Source handlers may create files within the synthetic home. Audit hooks are diagnostic tripwires rather than a security sandbox. Installed dependency code is reused and not fully attested. Production must consolidate this proof's process and connection primitives into the Rust owner. Never use this subset as evidence of complete retained startup or GUI parity.
