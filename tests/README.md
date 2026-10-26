# Running and maintaining tests

From the repository root, install the locked development environment with `uv sync --locked --extra dev`. uv selects Python 3.13 from `.python-version`; activation is not required. No model credentials are needed for local checks.

```sh
uv run --locked --extra dev python scripts/test.py                                  # fast
uv run --locked --extra dev python scripts/test.py --suite full                     # completion gate
uv run --locked --extra dev python scripts/test.py tests/kernel/action -k normalize # focused fast
uv run --locked --extra dev python scripts/test.py --suite full tests/agent          # focused integration
uv run --locked --extra dev python scripts/test.py --suite packaging                # templates and wheel
uv run --locked --extra dev ty check
```

`scripts/test.ps1 -Suite Fast/Full` and `scripts/typecheck.ps1` use the repository's locked uv environment from any working directory. They do not select a system Python or read `TINYSOUL_PYTHON`. If PowerShell blocks scripts, use the uv commands above or `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1`. Direct `uv run --locked --extra dev python -m pytest --suite fast/full` shares the same pytest hooks. In an activated project `.venv`, the uv prefix can be omitted. A path or `-k` filter narrows the selected suite; it never implicitly opts into integration, packaging or external work.

## Ownership and selection

Keep tests under their production owner's directory, named for the contract they protect. Unmarked tests belong to Fast. Mark real Agent/generation, local server and process collaboration `integration`; mark bundled assets, initialization and installation `packaging`. Full includes both and Fast. External tests require `--suite external` and their explicit opt-in switches; installed non-Python tools use `TINYSOUL_RUN_EXTERNAL_TOOLS=1`. Put real-provider modules in `test_real_*.py`: local suites exclude these before collection, so inherited API switches cannot load a personal project during local checks. Keep their `external` marker as well.

Test rules with small, explicit inputs. `support/actions.py::sample_catalog` owns its schema and policy values. `support/project.py::create_test_project` uses test-owned models and Home with real plugin resources. `copy_initialized_project` is for package resource contracts and integration that actually needs a distributed profile. Do not add snapshots of the current model IDs, provider names, prompt sentences or editable Action defaults. An adapter preserving an ID supplied by its test is a protocol assertion and is appropriate.

Reuse immutable inputs, not running Agents or mutable owner state. Put generally useful helpers in `support`; helper code used only by a module stays with that module. Avoid importing a test module from another test or reproducing the production scheduler/assembly in test helpers. Parametrize only behaviorally distinct cases. Cover a contract fully at its owner, then use a few representative cross-owner paths.

Source ownership/style guards use AST and remain in Fast. Tests for ordinary errors should assert structured reasons, owner keys and observable results; exact text assertions are reserved for actual protocols or text supplied by the test itself.

## Isolation and diagnosis

`conftest.py` is the sole owner of suite selection, asyncio backend, temporary environment, reports and cleanup. Every invocation creates `.local-test/runs/<uuid>` with independent pytest, temporary and instance directories. Local suites clear inherited `TINYSOUL_*` overrides before collection; External retains its explicit switches and project settings. Test files belong under `tmp_path`; subprocesses inherit the isolated environment and use `sys.executable`. Close and join processes, clients and Agents in fixture teardown or `finally`.

Use an event or a ready/completion message to coordinate concurrency. A watchdog bounds a failed test; it should not define the expected ordering. Local HTTP fixtures bind port 0 themselves and publish their bound endpoint after startup. Configuration tests provide their own environment mapping; proxy/credential inheritance tests explicitly arrange those inputs.

The terminal prints both the interpreter and artifact paths. JUnit, per-test durations and failure details remain in `.local-test/reports/<uuid>`. `latest-fast.json` and `latest-full.json` identify the most recent reports. Successful runs remove their large temporary directory; failed runs retain it. Use `--keep-artifacts` or the explicit `--artifact-root` override for diagnosis. No local results are committed.

An installed wheel check verifies the distribution separately from the source checkout. It does not resolve all dependencies in a fresh environment on every run; install the declared development dependencies before invoking the local gates.

## External checks

External checks contact real services or use extra executables. Select the suite and enable the relevant switch explicitly. For real model API checks, point to an initialized project's TOML and `.env`:

```powershell
$env:TINYSOUL_RUN_REAL_LLM_API = "1"
$env:TINYSOUL_REAL_PROJECT_ROOT = (Resolve-Path ../my-agent-dev).Path
uv run --locked --extra dev python scripts/test.py --suite external tests/llm/adapter/test_real_provider_api.py -s -ra --tb=short
```

Optionally set `TINYSOUL_REAL_MODELS` to comma-separated model IDs from that project and `TINYSOUL_REAL_PROVIDER` to an existing provider ID. Omitting models selects all configured models. Omitting the provider selects each model's first enabled binding with credentials. An explicit provider selects only its existing bindings and enables it inside the test process without editing TOML. Remove that variable to return to normal binding selection.

Missing bindings/credentials and undeclared capabilities are skipped; request failures remain failures and do not switch providers. The checks cover JSON, images, tool calls, reasoning continuation and cache telemetry. A missing cache-read measurement is unverified, not a cache hit; these checks do not establish cache expiry or Google cache-resource lifecycle behavior. The `-s -ra --tb=short` options show safe route/usage summaries.

Other external tests declare their opt-in switch in their `test_real_*.py` module. For checks of installed non-Python tools, set `TINYSOUL_RUN_EXTERNAL_TOOLS=1` and install the executables required by the chosen test. Reset external environment switches after use; Fast/Full independently clear them before collection.
