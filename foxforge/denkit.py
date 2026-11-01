"""Fox Den Midnight (DenKit v0.1) tokens for portable FoxForge views."""

from __future__ import annotations


TOKENS = {
    "midnight": "#0B1423",
    "slate": "#25384B",
    "mint": "#97E7CA",
    "coral": "#F68D91",
    "amber": "#F5AD66",
    "cream": "#F7F5E9",
    "raised": "#142335",
    "border": "#36495D",
    "muted": "#AFC0D1",
    "critical": "#EF5261",
}


def css() -> str:
    """Return self-contained CSS for static, offline review artifacts."""
    variables = "\n".join(f"  --den-{name}: {value};" for name, value in TOKENS.items())
    return f"""\
:root {{
{variables}
  color-scheme: dark;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}
* {{ box-sizing: border-box; }}
html {{ background: var(--den-midnight); color: var(--den-cream); }}
body {{
  margin: 0;
  min-height: 100vh;
  background: var(--den-midnight);
  color: var(--den-cream);
  line-height: 1.6;
}}
.shell {{ width: min(72rem, calc(100% - 2rem)); margin: 0 auto; padding: 2rem 0 4rem; }}
.skip-link {{
  position: absolute; left: 1rem; top: -4rem; z-index: 2;
  padding: .65rem 1rem; border-radius: .45rem;
  background: var(--den-mint); color: var(--den-midnight); font-weight: 750;
}}
.skip-link:focus {{ top: 1rem; outline: .2rem solid var(--den-cream); outline-offset: .15rem; }}
.masthead {{
  display: grid; gap: 1rem; padding: clamp(1.35rem, 4vw, 2.5rem);
  border: 1px solid var(--den-border); border-radius: .9rem;
  background: var(--den-raised);
}}
.brand {{ color: var(--den-coral); font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
h1, h2, h3 {{ margin: 0; line-height: 1.2; letter-spacing: -.015em; }}
h1 {{ font-size: clamp(2rem, 6vw, 3.75rem); }}
h2 {{ margin-bottom: 1rem; font-size: 1.35rem; }}
h3 {{ font-size: 1.05rem; }}
p {{ margin: .65rem 0 0; }}
.lede {{ max-width: 68ch; color: var(--den-muted); font-size: 1.05rem; }}
.status {{
  justify-self: start; display: inline-flex; align-items: center; gap: .5rem;
  padding: .4rem .75rem; border-radius: 999px;
  background: var(--den-amber); color: var(--den-midnight); font-weight: 800;
}}
.status::before {{ content: "◆"; font-size: .7rem; }}
.meta {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr)); gap: .75rem; margin: 1rem 0 0; }}
.meta div, .card {{
  border: 1px solid var(--den-border); border-radius: .75rem;
  background: var(--den-raised);
}}
.meta div {{ padding: .85rem 1rem; }}
.meta dt {{ color: var(--den-muted); font-size: .78rem; font-weight: 750; letter-spacing: .06em; text-transform: uppercase; }}
.meta dd {{ margin: .2rem 0 0; overflow-wrap: anywhere; }}
main {{ display: grid; gap: 1rem; margin-top: 1rem; }}
.card {{ padding: clamp(1rem, 3vw, 1.5rem); }}
.task-grid {{ display: grid; gap: .75rem; }}
.task {{ padding: 1rem; border-left: .25rem solid var(--den-coral); border-radius: .45rem; background: var(--den-slate); }}
.task-meta {{ display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .75rem; }}
.chip {{
  display: inline-flex; padding: .25rem .55rem; border: 1px solid var(--den-border);
  border-radius: 999px; background: var(--den-midnight); color: var(--den-mint);
  font: 700 .78rem ui-monospace, SFMono-Regular, Consolas, monospace;
}}
ul {{ padding-left: 1.3rem; }}
li + li {{ margin-top: .35rem; }}
code {{
  padding: .12rem .35rem; border-radius: .3rem;
  background: var(--den-midnight); color: var(--den-mint);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}}
.notice {{ border-left: .25rem solid var(--den-amber); }}
.notice strong {{ color: var(--den-amber); }}
.muted {{ color: var(--den-muted); }}
:focus-visible {{ outline: .2rem solid var(--den-mint); outline-offset: .2rem; }}
::selection {{ background: var(--den-coral); color: var(--den-midnight); }}
@media (max-width: 38rem) {{
  .shell {{ width: min(100% - 1rem, 72rem); padding-top: .5rem; }}
  .masthead, .card {{ border-radius: .65rem; }}
}}
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ scroll-behavior: auto !important; transition: none !important; }}
}}
"""
