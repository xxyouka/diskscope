# Icons

The stage-one interface uses a small monochrome icon set defined as SVG path
templates in `ui/components/icons.py`.  This keeps every glyph crisp at high
DPI and allows a single icon to be recolored for hover, active and dark
surfaces without shipping duplicate assets.

When the product adds platform file icons in the analysis stage, generated or
licensed raster assets can live in this folder.