# Project presentation

`configs/interface.toml` stores the project's shared theme, typography, density,
and motion preferences. The interface saves these settings through the backend
and applies them immediately. Other clients read the shared settings when they
connect, reopen the interface settings, or refresh. Agent reload is unnecessary.

Place shared presentation files under `assets/`, with subdirectories as needed.
The interface settings can list, preview supported images, and download these
files. Asset files do not automatically become font options or executable UI.
The asset directory may be absent when there are no files.

These files belong to the project. Package templates are copied only during
initialization/reset. `tinysoul reset` restores this directory along with the
rest of the project and preserves only `.env`.
