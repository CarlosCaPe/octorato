# Cotizacion (quote / proposal) generator

Brand-neutral engine that renders a professional service quote as a `.docx` (and a
`.pdf` via LibreOffice). This is the fachada/cimientos pattern: the invariant layout
engine lives here in the public brain, and every brand or content specific value is
supplied at run time through a config file.

The engine carries no company name, no colors, no font choice, no rates, and no
client data of its own. All of that is config.

## What is generic vs what is yours

| Generic (lives here, public) | Yours (lives in a PRIVATE config) |
|---|---|
| Layout: cover, letter, about page, sections, tables, signature, footer | Company name, founder, email, portfolio |
| Helper builders and OOXML machinery | Colors, font, logo, signature image |
| Block renderer (paragraph, bullet, table, note, ...) | Section copy, rates, investment tables |
| PDF conversion | Dates, validity, legal clausulado |

> WARNING. Real brand assets (brand colors, logo, the SIGNATURE image, and your
> legal clausulado) must live in the private `company/` dir or inside the client
> arm, NEVER in this public template. The only image shipped here is
> `assets/signature.example.png`, a generated placeholder that is not anyone's real
> signature. The example rate (USD 50/hr) is invented.

## Install

    pip install python-docx lxml pyyaml
    sudo apt install -y libreoffice-writer   # only needed for PDF output

## Run the demo

    python3 cotizacion_engine.py --config config.example.yaml

That reads the brand-neutral example and writes `out/Quote_Sample_Engagement_Acme.docx`
plus a `.pdf` next to it. Add `--no-pdf` to skip the PDF step.

## Wire your own brand and content

1. Copy `config.example.yaml` to a private location (your `company/` dir or the arm),
   for example `company/cotizacion/acme.yaml`. Do not commit it to the public brain.
2. Replace the `brand` block with your real company, font, colors, and the path to
   your real signature image (kept private).
3. Replace `cover`, `intro_letter`, `about`, `sections`, `validity`, `signature`,
   and `footer` with your real content. Paste your real clausulado into `footer`
   and into the terms sections.
4. Generate:

       python3 /path/to/cotizacion_engine.py --config company/cotizacion/acme.yaml

You can also drive the engine as a library:

    from cotizacion_engine import CotizacionEngine
    engine = CotizacionEngine(brand, content, base_dir="company/cotizacion")
    docx_path, pdf_path = engine.build("out/quote.docx")

## Config shape

- `brand`: `company`, `founder`, `founder_title`, `email`, `portfolio`, `font`,
  `template_docx` (optional base .docx for a themed footer, or null), `signature_image`,
  `colors` (hex strings), `sizes` (points).
- `document`: `proposal_date`, `proposal_date_long`, `footer_date`.
- `cover`, `intro_letter`, `about`, `validity`, `signature`, `footer`: house sections.
- `sections`: a list, each with a `heading` and a list of `blocks`. Set
  `page_break_before: true` on a section to start it on a new page.

### Block types

- `paragraph`: `text`, optional `bold`, `italic`, `align`, `space_after`.
- `lead`: a colored bold `label` followed by `body` text in one paragraph.
- `subheading`: an H3 heading.
- `bullet`: a bullet with an optional bold `label` and a `body`.
- `table`: `headers`, `rows`, optional `col_widths_cm`. Cells support `**bold**` spans.
- `note`: small italic caption.
- `spacer`: vertical space.

### Placeholders

- `{{company}}` inside an `intro_letter` paragraph or the `about` intro is replaced
  with the brand company name rendered in the accent color.
