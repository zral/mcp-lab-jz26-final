# Architecture diagrams

Mermaid source for the diagrams used in the presentation. The `.mmd` files are
the source; the `.png` files are generated and must not be edited by hand.

| File | Used on slide |
| --- | --- |
| `01-architecture.mmd` | System Architecture |
| `02-deployment.mmd` | Deployment |
| `03-startup.mmd` | Data Flow – Startup |
| `04-dataflow.mmd` | Data Flow – Request |

## Re-rendering

```bash
make diagrams          # only the ones that changed
make diagrams-force    # all of them
make slides            # diagrams + presentation HTML
```

Requires `npx` (ships with Node). `@mermaid-js/mermaid-cli` is downloaded on demand.

## Why the source lives in the repo now

The previous diagrams existed only as PNGs on Cloudinary, with no source
anywhere. The result was that they drifted away from the code without anyone
noticing: two of them still showed **OpenWeatherMap** long after the
implementation had moved to yr.no, and one documented a code path that was dead.
With the source here, that kind of drift gets caught in review.

See `doc/mcp-2026-07-28-corrections.md` § B7 for what was concretely wrong.

## Two pitfalls

**Marp does not render Mermaid.** Verified 2026-08-23: a ` ```mermaid ` block in
a Marp slide comes out as a `<pre>` code block, not as a diagram. Hence the
intermediate `.png` step.

**Underscores in sequence messages.** Mermaid reads `_` in message text as
emphasis. `_meta` on its own turned into an underlined "meta". Neither `#95;`
nor `&#95;` helps — the first is ignored, the second yields a stray `&`. The fix
used here is to write `params._meta`, which both avoids the problem and is more
precise: the field lives inside `params`.

## The HTML is not self-contained

The presentation HTML references `./diagrams/*.png` relatively, unlike before
when the images lived on Cloudinary. If you move the `.html` file, the
`diagrams/` directory has to come with it.
