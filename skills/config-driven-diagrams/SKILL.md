---
name: config-driven-diagrams
description: "Build config-driven architecture diagrams as dark-themed SVG/PNG with swimlanes, embedded logos, auto-layout, and overlap validation. Use when the user asks for architecture diagrams, data flow diagrams, system topology, or any visual diagram that should be rendered programmatically from a JSON config. Trigger on: diagram, architecture diagram, data flow, swimlane, render SVG, render PNG, system diagram, topology."
metadata:
  short-description: Config-driven SVG/PNG architecture diagrams
  origin: client project (anonymized pattern)
---

# Config-Driven Architecture Diagrams

## Purpose

Render professional dark-themed architecture diagrams from a declarative JSON config.
No manual drawing — define lanes, nodes, arrows, and logos in JSON; the renderer
produces SVG (and optionally PNG via Playwright).

## When to Use

- Architecture overview diagrams (data platform, microservices, ETL flows)
- Data flow diagrams with swimlanes (Bronze → Silver → Gold, etc.)
- System topology with tech-specific logos and palettes
- Any diagram that needs to be version-controlled and reproducible

## Architecture

```
diagram.json (config)  →  render-diagram.js  →  output.svg + output.png
                              ↑
                        shared/logos/*.svg   (embedded as base64)
```

## Config Schema

```jsonc
{
  "name": "my-architecture",         // filename prefix
  "title": "System Architecture",    // main heading
  "subtitle": "Team · Date",         // optional subheading
  "width": 1600,                     // canvas width (px)
  "height": 1100,                    // canvas height (px)
  "nodeHeight": 100,                 // card height (default: 100)
  "gap": 32,                         // compact gap between nodes
  "padding": 20,                     // inner swimlane padding

  "lanes": [                         // swimlanes (left to right)
    {
      "x": 20,                       // lane X position
      "width": 290,                  // lane width
      "label": "DATA SOURCES",       // header text
      "number": "①",                 // header prefix
      "bgColor": "#1A1520",          // optional background override
      "headerColor": "#C62828",      // optional header override
      "columns": [                   // sub-columns within lane
        {
          "distribution": "even",    // "even" | "compact-top" | "compact-bottom"
          "arrows": true,            // draw vertical arrows between nodes
          "arrowType": "data",       // "data" (solid blue) | "auth" (dashed gray)
          "arrowLabels": ["ingest", "clean"],
          "frame": {                 // optional dashed border
            "label": "SQL Server",
            "color": "#CC2927"
          },
          "nodes": [
            {
              "name": "source_db",
              "subtitle": "Core operational DB",
              "logo": "mssql",       // key from logo map
              "palette": "mssql",    // key from palette map
              "tag": "SERVICE",      // bottom-right tag
              "badge": {             // optional top-right badge
                "label": "PROD",
                "bg": "#2E7D32",
                "color": "#A5D6A7"
              }
            }
          ]
        }
      ]
    }
  ],

  "arrows": [                        // cross-lane arrows
    {
      "type": "data",                // "data" | "auth" | "curved"
      "x1": 310, "y1": 168,
      "x2": 530, "y2": 168,
      "label": "batch / CDC"
    }
  ]
}
```

## Standard Palettes (22)

| Key | Stroke | Use For |
|-----|--------|---------|
| `mssql` | `#CC2927` | SQL Server |
| `ingestion` | `#0078D4` | Azure, ADF |
| `bronze` | `#CD7F32` | Bronze layer |
| `silver` | `#A8B5C0` | Silver layer |
| `gold` | `#DAA520` | Gold layer |
| `delta` | `#00ADD8` | Delta tables |
| `uniform` | `#00ACC1` | UniForm, protocol bridges |
| `api` | `#4E8EE9` | REST APIs |
| `auth` | `#5C6BC0` | Auth, security |
| `spark` | `#E25A1C` | Apache Spark |
| `snowflake` | `#29B5E8` | Snowflake |
| `postgres` | `#336791` | PostgreSQL |
| `kafka` | `#231F20` | Kafka |
| `redis` | `#DC382D` | Redis |
| `kubernetes` | `#326CE5` | Kubernetes |
| `terraform` | `#7B42BC` | Terraform |
| `python`/`pyiceberg` | `#BA68C8` | Python tools |
| `dotnet` | `#512BD4` | .NET |
| `react` | `#61DAFB` | React |
| `trino` | `#DD00A1` | Trino, Flink |
| `duckdb` | `#FFC107` | DuckDB |
| `generic` | `#546E7A` | Default |

## Badge Conventions

| Status | bg | color | Example |
|--------|-----|-------|---------|
| Complete | `#2E7D32` | `#A5D6A7` | `{ "label": "COMPLETE", "bg": "#2E7D32", "color": "#A5D6A7" }` |
| Blocked | `#B71C1C` | `#EF9A9A` | `{ "label": "BLOCKED", "bg": "#B71C1C", "color": "#EF9A9A" }` |
| In Progress | `#E65100` | `#FFE0B2` | `{ "label": "IN PROGRESS", "bg": "#E65100", "color": "#FFE0B2" }` |
| Not Started | `#37474F` | `#90A4AE` | `{ "label": "NOT STARTED", "bg": "#37474F", "color": "#90A4AE" }` |

## Layout Engine Rules

### Swimlanes
- Vertical lanes, left to right
- Each lane gets a colored header bar + dark background
- Internal columns for multi-column layouts within a lane

### Node Distribution
- **even**: Space nodes evenly in available vertical space
- **compact-top**: Pack nodes from top
- **compact-bottom**: Pack nodes from bottom

### Overlap Validation
- All node rectangles are checked before rendering
- Build fails with error if any overlap detected
- Formula: `nodeHeight * maxNodes + gap * (maxNodes-1) + 170` for height

### Cross-Lane Arrows
- `data`: solid blue line (data flow)
- `auth`: dashed gray line (auth/config)
- `curved`: bezier curve with custom color + opacity

## Adding Logos

1. Save SVG/PNG to a `logos/` directory
2. Register in `LOGO_MAP` with a key name
3. Add matching palette if needed
4. Logo renders as 36×36 badge with rounded background

## CLI Usage

```bash
# SVG only
node render-diagram.js --config diagram.json

# SVG + PNG (requires Playwright)
node render-diagram.js --config diagram.json --png

# Custom output directory
node render-diagram.js --config diagram.json --png --out ./output
```

## Tips

1. **Width planning**: Sum all `lane.x + lane.width`. Add 20px margins
2. **Height planning**: Use the overlap formula. Start tall, shrink to fit
3. **Fan-out**: Use curved arrows from one source to multiple targets
4. **Frames**: Group related nodes with `column.frame` (dashed border)
5. **Badges**: Environment indicators (PROD, DEV, BETA)
6. **Tags**: Categorize nodes (SERVICE, LAYER, PROTOCOL, CLIENT)
7. **Config arrays**: Put multiple diagram objects in one JSON file for batch rendering

## Reference Implementation

The original renderer is a ~490-line Node.js script that:
- Parses CLI args for config path, PNG flag, output dir
- Defines design tokens (dark theme colors, fonts, sizes)
- Loads logos from filesystem and base64-encodes them
- Renders SVG with swimlane headers, node cards, arrows, legend
- Optionally launches Playwright for PNG screenshot at 2x DPR
- Validates no rectangle overlaps before output

Adapt this pattern for any project that needs reproducible architecture diagrams.

## Lessons Learned

- **Dark theme is better for presentations** — high contrast, looks professional on projectors
- **Config > code** — changing diagram layout via JSON is 10x faster than editing SVG code
- **Overlap validation saves hours** — catch layout bugs at build time, not after sharing
- **Playwright PNG** — 2x DPR gives crisp output for docs and wikis
- **Base64 logos** — embed SVGs directly in the output → single self-contained file
- **Radial layout center node**: In radial layouts, the center node stacks logo → name → subtitle → tag vertically. The renderer uses a sequential `contentY` tracker to avoid overlap. **Rule**: `center.height >= logoSize + 100` to leave room for name + subtitle + tag
- **Logo SVGs with explicit fill**: Custom SVG logos must NOT include `fill` attributes on path elements. The renderer applies fill via `wrapInBadge()`. If the SVG has its own fill matching the badge background, the icon becomes invisible (solid color block). Always use monochrome SVGs without fill
- **Content-aware sizing**: Allocate lane widths proportionally to content (`longest subtitle * 7.5px + 70px`). Auth nodes go top, consumers bottom
