# Fox Den Midnight in FoxForge

FoxForge uses the Workspace variant of Fox Den Midnight (DenKit v0.1) for its
human-review plan artifact. `plan.html` is a self-contained, offline document:
it loads no fonts, scripts, images, or external styles and grants no new action.
The existing Markdown and JSON artifacts remain the compatibility formats.

## Tokens

| Token | Value | Use |
| --- | --- | --- |
| Midnight | `#0B1423` | Page background |
| Slate | `#25384B` | Dense task surfaces |
| Mint | `#97E7CA` | Focus, technical metadata, healthy emphasis |
| Coral | `#F68D91` | Brand and selected task accents |
| Amber | `#F5AD66` | Review-pending and authorization notices |
| Cream | `#F7F5E9` | Primary foreground text |
| Raised Surface | `#142335` | Cards and navigation surfaces |
| Border | `#36495D` | Dividers and outlines |
| Muted Text | `#AFC0D1` | Supporting information |
| Critical Red | `#EF5261` | Reserved for errors and destructive actions |

The canonical values live in `foxforge/denkit.py`. Bright backgrounds use dark
Midnight text. Statuses always include text and shape as well as color. The view
uses system fonts, responsive layout, visible keyboard focus, and reduced-motion
handling without introducing a frontend dependency.

## Scope

DenKit v0.1 applies to the static plan review surface only. A future dashboard
can consume the same semantic tokens, but this change does not add a server,
authentication surface, JavaScript runtime, or dashboard architecture.
