# Running and maintaining tests

Use the project's Python with `.[dev]` installed. No model credentials are needed for local checks.

```sh
python scripts/test.py                                  # fast
python scripts/test.py --suite full                     # completion gate
python scripts/test.py tests/kernel/action -k normalize # focused fast
python scripts/test.py --suite full tests/agent          # focused integration
python scripts/test.py --suite packaging                # templates and wheel
python -m ty check
```

`scripts/test.ps1 -Suite Fast/Full` and direct `python -m pytest --suite fast/full` share the same pytest hooks. The Python entry uses its own interpreter; the PowerShell wrapper accepts `TINYSOUL_PYTHON`. A path or `-k` filter narrows the selected suite; it never implicitly opts into integration, packaging or external work.

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
