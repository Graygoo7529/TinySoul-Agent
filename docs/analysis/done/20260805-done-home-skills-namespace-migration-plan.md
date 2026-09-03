# Home Skills Namespace Refactor

## Status

status: done

## Goal

Remove the Home `what` and `why` namespaces and rename the general and
framework-local `how` namespaces to `skills`, `skills_domain`, and
`skills_action`. This is a clean development-stage break: no aliases, dual
reads, upgrade migration, or compatibility layer are introduced.

## Target Contract

| Link | Physical path |
| --- | --- |
| `home:agent@<path>` | `agent/<path>.md` |
| `home:skills@<skill>` | `skills/<skill>/SKILL.md` |
| `home:skills/<skill>/<resource>` | `skills/<skill>/<resource>` |
| `home:skills_domain:<domain>` | `skills_domain/<domain>/DOMAIN.md` |
| `home:skills_action:<domain>/<action>` | `skills_action/<domain>/<action>.md` |

Only `agent` and `skills` are Home top spaces. `skills_domain` and
`skills_action` are prompt-mount identities only. `what`, `why`, `how`,
`how_domain`, and `how_action` are invalid in the current implementation.

## Scope

1. Update Home link parsing, layout mapping, effective catalog/search,
   overlay validation, skill-memory paths, review payloads, and exports.
2. Rename current code-level `*HowProvider`/`ActionHow` protocol names and
   prompt labels to skill terminology without compatibility aliases.
3. Update Loop, Action, App, Script capability, action Catalog, package-data,
   default Home assets, current design documents, and current tests.
4. Keep `home.top.*` and `home.prompt_mount.*` action identities unchanged in
   this namespace refactor; their intent-based action review is separate.
5. Do not implement Memory entity/concept/fact/note links in this change.

## Content Decision

The default `what` and `why` files are removed as Home entries. Framework
explanations required by the default agent are rewritten into the existing
documentation skill/reference or developer design docs without preserving
WHAT/WHY Link identities. Personal or project-specific WHAT content has no
automatic migration path in this change.

## Strict Break

Old links and old physical namespaces are not recognized. Existing runtime
overlay records are not rewritten. The implementation may fail clearly when
old data is encountered, but it must not silently expose it, alias it, or
delete it as a migration side effect.

## Verification

Focused Home, Loop, Action, Script, Context, Memory, initializer, and wheel
tests must use only the new contract. Completion requires the Fast suite,
`scripts/test.ps1 -Suite Full`, and `scripts/typecheck.ps1`.

Completed on 2026-08-05:

- Focused Home suite: 69 passed.
- Cross-module focused regression: passed with the existing skipped cases.
- Fast suite: 863 passed, 2 skipped, 22 deselected.
- Full suite: 864 passed, 2 skipped, 21 deselected.
- Type check: all checks passed.
- Current source, package data, root guidance, and design docs contain no old
  Home link, provider, prompt-mount, or review-kind identifiers. Tests retain
  only explicit assertions that the removed namespaces are rejected or absent.

## Post-Implementation Alignment Audit

The 2026-08-05 follow-up audit aligned the remaining current App API reference
and the active visualization capability plan, removed empty legacy directories
from the default Home asset tree, and renamed the last test identifier that
described prompt mounts as HOW spaces. Historical chat, archive, and completed
analysis records retain their original terminology as dated design evidence.
