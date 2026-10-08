# Managed V3 authentication and observation overlay

This is an inactive build candidate for TabbyAPI commit
`2fd6cc76203a66e13042daf7d76e5898b21c1ad8`. It changes no installed runtime.
`build_overlay.py` accepts only the pinned auth, networking, model schema,
backend observation and license contents and
writes to a new directory outside the source pack. Its manifest attests those
selected files, not a complete runtime environment. Existing generated candidates
are immutable snapshots; rebuild to a new output directory after source changes.

The managed contract is `hermes-native-observation-v1`. Its runtime-pack identity
combines that contract with the upstream commit. The inference controller
requires this contract: stock Tabby model responses do not prove that drafting
is disabled. The overlay adds `parameters.hermes_native_draft_enabled`, computed
from both the backend's draft-model flag and its n-gram drafting setting. The
controller accepts only the actual Boolean `false`; missing or ambiguous values
do not qualify a runtime for loading/generation admission. This field describes
effective backend state; it does not attest model bytes or the whole runtime.

The replacement retains `load_auth_keys`, `check_api_key`, `check_admin_key` and
`get_key_permission`. FastAPI dependencies and the permission helper use the same
raw-header parser. Exactly one occurrence across `Authorization`, `X-API-Key` and
`X-Admin-Key` is required, including empty occurrences. Duplicates and conflicting
carriers return HTTP 401 before route handlers run. Bearer syntax is required for
`Authorization`; the token value determines the `api` or `admin` role regardless
of carrier. API tokens cannot perform admin operations. Uninitialized auth returns
503. There is no auth-disabled path, token-file fallback, key watcher or key log.

The owner provides distinct cryptographically random values through
`HERMES_TABBY_API_KEY` and `HERMES_TABBY_ADMIN_KEY` in the explicit worker
environment. Each must contain 32–4096 printable ASCII characters without spaces
or control characters. Generate URL-safe tokens; never put real values in YAML,
arguments, logs, source, renderer state or fixtures. Rotation requires an owned
worker restart. Initialization removes these two environment variables from the
worker after consumption; the owner retains its separately scoped credentials.

## Startup constraints

`config/managed-tabby-v3.yml` is a non-secret template, not an activated config.
It is checked against the SHA-256-pinned `common/config_models.py`. For eventual
integration:

1. Construct a separate, verified managed runtime with the new overlay files.
   Do not install this overlay into the user's running runtime.
2. Use the owned worker launcher with an absolute executable, a controlled working
   directory and an explicit environment allowlist. Do not inherit arbitrary
   `TABBY_*` configuration overrides, Python path hooks, or unrelated secrets.
3. Supply the absolute managed template path through Tabby's `--config` argument.
   Its loader reads working-directory `config.yml`, then environment overrides,
   then this explicitly selected file. An explicit file takes precedence and
   causes other argument overrides to be ignored. Keep the working directory
   free of unrelated user configuration; validate the effective policy before
   eventually marking the worker ready. A template alone does not enforce the
   launcher's behavior.
4. Keep the explicit empty strings for model, draft and embedding names. The
   pinned loader removes `null` values before merging; `null` would fail to clear
   a model name from a lower-precedence source. Empty strings survive merging and
   the startup `if model_name`/`if embedding_model_name` checks skip loading.
   Inline model loading is disabled so generation cannot bypass model control.
5. Keep loopback binding, auth enabled, empty browser-origin allowlist, traceback
   responses disabled, and all raw access/request/chat/prompt/parameter/Seq
   logging disabled. The overlay sanitizes `log_request` only; the inactive
   template disables the other request-content logging paths. Do not describe
   the overlay alone as universal runtime log redaction.
6. Port 5000 is a template value. The coordinator must choose and validate its
   managed port without adopting or terminating an unrelated process. Startup
   still requires authenticated readiness. No runtime was started to test this.

Upstream calls auth initialization after optional startup model/embedding loads.
No-autoload policy avoids those loads before auth. Removing keys from the
environment at initialization cannot erase earlier copies or guarantee no
startup subprocess inherited them. The owner must restrict startup code and
the runtime environment. No model, GPU, process launch, V2 support, or VRAM
release is certified by this spike.

## Verification

Run from this staging directory after activation:

```powershell
. 'G:\Project_Ned\.venv\Scripts\Activate.ps1'
python -m pytest -c pytest.ini -o addopts='' tests --basetemp=.pytest-tmp -q
python -m ruff check build_overlay.py overlay tests config
python -m ruff format --check build_overlay.py overlay tests config
python config/validate_template.py --schema G:\Project_Ned\runtime\tabbyAPI\common\config_models.py
```

The suite uses synthetic credentials, in-memory ASGI requests and temporary test
files. Canonical-path builder tests may need scoped sandbox elevation on this
Windows machine. The schema validator imports only the hash-verified pure
Pydantic schema; it does not import or launch the inference runtime.
