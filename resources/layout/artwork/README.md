# Extracted layout artwork

This directory is generated from the two HTML exports in the parent folder.

- parts/ contains deduplicated transparent PNG layers.
- layout_artwork_manifest.json stores exact geometry, z-order, group hierarchy, opacity, blend modes, transforms, visibility, filters, isolation and embedded-image style settings.
- LAYOUT_MIGRATION_REPORT.md compares both exports and lists every layer.

The canvas is 1920×1440 with a top-left origin. The full export has 23 layers; the simple export has 18. They share 18 identical positioned layer instances, and five layers occur only in the full export.

These artwork coordinates are distinct from printable-area masks in layout_profiles.json. The HTML frame image is [217, 188, 1539, 1246]; the legacy profile rectangle is [299, 191, 1621, 1249].

The build-layout-artwork-assets GitHub Actions workflow regenerates and commits this directory whenever either HTML source or the extractor changes. Keep the HTML source files until a visual reconstruction is verified.
