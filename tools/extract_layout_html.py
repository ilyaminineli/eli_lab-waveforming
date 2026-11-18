#!/usr/bin/env python3
"""Extract two WAVEFORMING PSD-to-HTML plates into PNG parts and exact geometry."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from collections import Counter
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path

from PIL import Image

ID_RE = re.compile(r"^(page|group|image)_\d+$")
PX_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)px\s*$", re.I)
ROTATE_RE = re.compile(r"rotate\(\s*(-?\d+(?:\.\d+)?)deg\s*\)", re.I)
DATA_URI_RE = re.compile(
    r"""url\(\s*(['"]?)(data:image/[^)'"]+;base64,[A-Za-z0-9+/=\s]+)\1\s*\)""",
    re.I | re.S,
)


def style_map(value: str) -> dict[str, str]:
    result = {}
    for declaration in value.split(";"):
        if ":" in declaration:
            key, val = declaration.split(":", 1)
            if key.strip():
                result[key.strip().lower()] = val.strip()
    return result


def px(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    match = PX_RE.match(value)
    return float(match.group(1)) if match else default


def embedded_image(style: str):
    match = DATA_URI_RE.search(style)
    if not match:
        return None
    header, encoded = match.group(2).split(",", 1)
    mime = header[5:].split(";", 1)[0].lower()
    payload = base64.b64decode(re.sub(r"\s+", "", encoded), validate=True)
    return mime, payload


class PlateParser(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, output: Path, shared_assets: dict):
        super().__init__(convert_charrefs=True)
        self.output = output
        self.shared_assets = shared_assets
        self.stack = []
        self.page = None
        self.groups = []
        self.layers = []
        self.tags = Counter()
        self.unresolved = []
        self.order = 0

    def _active_layer(self):
        for node in reversed(self.stack):
            if node.get("layer") is not None:
                return node["layer"]
        return None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags[tag] += 1
        identifier = attrs.get("id", "")
        style = style_map(attrs.get("style", ""))
        parent_id = next((node["id"] for node in reversed(self.stack) if node["id"]), None)
        order = self.order
        self.order += 1
        node = {"tag": tag, "id": identifier, "style": style, "order": order}

        if ID_RE.match(identifier):
            kind = identifier.split("_", 1)[0]
            if kind == "page":
                self.page = node
            elif kind == "group":
                self.groups.append({
                    "id": identifier, "parent_id": parent_id,
                    "dom_order": order, "style": style,
                })
            elif kind == "image":
                layer = {
                    "id": identifier, "parent_id": parent_id,
                    "dom_order": order, "z_order": len(self.layers),
                    "outer_style": style, "image_style": {}, "asset": None,
                }
                self.layers.append(layer)
                node["layer"] = layer

        active = self._active_layer()
        if active is not None and "background-image" in style and active["asset"] is None:
            embedded = embedded_image(attrs.get("style", ""))
            if embedded:
                mime, payload = embedded
                digest = hashlib.sha256(payload).hexdigest()
                asset = self.shared_assets.get(digest)
                if asset is None:
                    with Image.open(BytesIO(payload)) as image:
                        dimensions = list(image.size)
                        image_format = image.format
                        image.verify()
                    extension = "png" if mime == "image/png" else "jpg"
                    filename = f"layer_{digest[:16]}.{extension}"
                    parts = self.output / "parts"
                    parts.mkdir(parents=True, exist_ok=True)
                    (parts / filename).write_bytes(payload)
                    asset = {
                        "sha256": digest, "file": f"parts/{filename}",
                        "bytes": len(payload), "mime": mime,
                        "format": image_format, "size_px": dimensions,
                    }
                    self.shared_assets[digest] = asset
                active["asset"] = asset
                active["image_style"] = {
                    key: value for key, value in style.items()
                    if key != "background-image"
                }
                active["image_style"]["background-image"] = f"url('{asset['file']}')"

        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def finish(self, source: Path):
        if not self.page:
            raise ValueError(f"{source} has no page_N element")
        page_style = self.page["style"]
        width, height = px(page_style.get("width")), px(page_style.get("height"))
        if not width or not height:
            raise ValueError(f"{source} has no explicit page dimensions")

        group_by_id = {group["id"]: group for group in self.groups}
        layers = []
        for layer in self.layers:
            asset = layer["asset"]
            if asset is None:
                self.unresolved.append(layer["id"])
                continue
            style = layer["outer_style"]
            x, y = px(style.get("left")), px(style.get("top"))
            w, h = px(style.get("width")), px(style.get("height"))
            rotation = ROTATE_RE.search(style.get("transform", ""))
            parent_id = layer["parent_id"]
            group_path = []
            absolute_x, absolute_y, group_opacity = x, y, 1.0
            ancestor_visible = True
            while parent_id in group_by_id:
                group = group_by_id[parent_id]
                group_path.append(parent_id)
                gs = group["style"]
                absolute_x += px(gs.get("left"))
                absolute_y += px(gs.get("top"))
                group_opacity *= float(gs.get("opacity", "1"))
                ancestor_visible &= gs.get("display", "block") != "none"
                parent_id = group["parent_id"]
            group_path.reverse()
            opacity = float(style.get("opacity", "1"))
            display = style.get("display", "block")
            layers.append({
                "id": layer["id"], "parent_id": layer["parent_id"],
                "group_path": group_path, "dom_order": layer["dom_order"],
                "z_order": layer["z_order"], "asset_file": asset["file"],
                "asset_sha256": asset["sha256"], "asset_size_px": asset["size_px"],
                "rect_px": [x, y, w, h],
                "absolute_rect_px": [absolute_x, absolute_y, w, h],
                "rotation_deg": float(rotation.group(1)) if rotation else 0.0,
                "transform_origin": style.get("transform-origin", "top left"),
                "opacity": opacity, "group_opacity_product": group_opacity,
                "effective_opacity_if_groups_are_flattened": opacity * group_opacity,
                "blend_mode": style.get("mix-blend-mode", "normal").lower(),
                "display": display,
                "visible": display != "none" and opacity > 0 and ancestor_visible,
                "filter": style.get("filter", "none"),
                "isolation": style.get("isolation", "auto"),
                "outer_style": style, "image_style": layer["image_style"],
            })

        groups = []
        for group in self.groups:
            style = group["style"]
            groups.append({
                "id": group["id"], "parent_id": group["parent_id"],
                "dom_order": group["dom_order"],
                "position_px": [px(style.get("left")), px(style.get("top"))],
                "opacity": float(style.get("opacity", "1")),
                "display": style.get("display", "block"),
                "visible": style.get("display", "block") != "none",
                "isolation": style.get("isolation", "auto"),
                "filter": style.get("filter", "none"), "style": style,
            })

        return {
            "source": source.name, "source_bytes": source.stat().st_size,
            "source_sha256": sha256_file(source),
            "canvas_size_px": [int(width), int(height)],
            "page": {
                "id": self.page["id"],
                "background_color": page_style.get("background-color", "transparent"),
                "style": page_style,
            },
            "html_tag_counts": dict(self.tags),
            "group_count": len(groups), "layer_count": len(layers),
            "embedded_image_count": sum(1 for item in self.layers if item["asset"]),
            "unresolved_layers": self.unresolved,
            "groups": groups, "layers": layers,
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def inspect(source: Path, output: Path, shared_assets: dict):
    parser = PlateParser(output, shared_assets)
    with source.open("r", encoding="utf-8", errors="replace") as handle:
        while chunk := handle.read(1024 * 1024):
            parser.feed(chunk)
    parser.close()
    return parser.finish(source)


def layer_signature(layer):
    return (layer["asset_sha256"], tuple(layer["absolute_rect_px"]),
            layer["rotation_deg"], round(layer["opacity"], 9), layer["blend_mode"])


def compare(full, simple):
    simple_counts = Counter(layer_signature(layer) for layer in simple["layers"])
    full_counts = Counter(layer_signature(layer) for layer in full["layers"])
    common = simple_counts & full_counts

    def unmatched(source, other):
        counts = Counter(layer_signature(layer) for layer in other["layers"])
        result = []
        for layer in source["layers"]:
            key = layer_signature(layer)
            if counts[key]:
                counts[key] -= 1
            else:
                result.append(layer["id"])
        return result

    return {
        "variant_order": [full["source"], simple["source"]],
        "matching_layer_instances": sum(common.values()),
        "full_only_layer_ids": unmatched(full, simple),
        "simple_only_layer_ids": unmatched(simple, full),
        "note": "Layers matched by image SHA-256, absolute rectangle, rotation, opacity and blend mode.",
    }


def make_report(manifest):
    full, simple = manifest["variants"]
    comparison = manifest["comparison"]
    lines = [
        "# WAVEFORMING HTML layout migration report", "",
        "Native top-left canvas geometry is preserved in 1920×1440 pixel coordinates.", "",
        "## Findings", "",
        f"- layout.html: {full['layer_count']} image layers, {full['group_count']} groups, {full['source_bytes']:,} bytes.",
        f"- layout_simple.html: {simple['layer_count']} image layers, {simple['group_count']} groups, {simple['source_bytes']:,} bytes.",
        f"- Deduplicated embedded PNGs: {len(manifest['assets'])} unique assets, {sum(a['bytes'] for a in manifest['assets'].values()):,} bytes.",
        f"- Identical positioned layer instances: {comparison['matching_layer_instances']}.",
        f"- Full-only layers: {', '.join(comparison['full_only_layer_ids']) or 'none'}.",
        f"- Simple-only layers: {', '.join(comparison['simple_only_layer_ids']) or 'none'}.",
        "", "## Preserve", "",
        "Keep page size, image assets, source rectangles, accumulated group offsets, DOM z-order, group paths, opacity, blend modes, rotation, transform origin, visibility, filters, isolation and nested image styles.",
        "The 1322×1058 artwork frame in the HTML files is [217, 188, 1539, 1246]. The legacy printable-area rectangle in layout_profiles.json is [299, 191, 1621, 1249]. These values have different provenance and must not be conflated.",
        "resources/screens/pre_designed/Scr1.png through Scr7.png are separate pre-rendered screens, not substitutes for these HTML layers.",
        "", "## Layer inventories", "",
    ]
    for variant in (full, simple):
        lines += [
            f"### {variant['source']}", "",
            "| Z | Layer | Group path | Absolute rect [x,y,w,h] | Opacity | Blend | Asset |",
            "|---:|---|---|---|---:|---|---|",
        ]
        for layer in variant["layers"]:
            rect = ", ".join(str(int(v) if float(v).is_integer() else v)
                             for v in layer["absolute_rect_px"])
            lines.append(
                f"| {layer['z_order']} | {layer['id']} | "
                f"{'/'.join(layer['group_path']) or 'page'} | {rect} | "
                f"{layer['opacity']:.6g} | {layer['blend_mode']} | {layer['asset_file']} |"
            )
        lines.append("")
    lines += [
        "## Deletion guidance", "",
        "The HTML exports are static wrappers around embedded images and inline styles. They are no longer required at runtime once the extracted parts and manifest are committed and a visual reconstruction is checked against both source variants. Keep the HTML files until that verification is complete.",
    ]
    return "\n".join(lines) + "\n"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("full", type=Path)
    cli.add_argument("simple", type=Path)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    assets = {}
    variants = [
        inspect(args.full, args.output, assets),
        inspect(args.simple, args.output, assets),
    ]
    if variants[0]["canvas_size_px"] != variants[1]["canvas_size_px"]:
        raise SystemExit("The variants use different canvas sizes.")
    if any(variant["unresolved_layers"] for variant in variants):
        raise SystemExit("An image layer has no embedded asset.")
    manifest = {
        "schema_version": 1,
        "coordinate_system": {
            "units": "pixels", "origin": "top-left",
            "canvas_size_px": variants[0]["canvas_size_px"],
            "position_semantics": "absolute left/top after accumulated group offsets",
            "layer_order_semantics": "DOM order, lower z_order is drawn first",
        },
        "variants": variants, "comparison": compare(*variants), "assets": assets,
        "notes": [
            "PNG parts are deduplicated by SHA-256.",
            "Group effects must be applied at group level for exact isolated-group reproduction.",
            "The artwork manifest is separate from layout_profiles.json printable-area masks.",
        ],
    }
    (args.output / "layout_artwork_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "LAYOUT_MIGRATION_REPORT.md").write_text(
        make_report(manifest), encoding="utf-8")
    print(json.dumps({
        "unique_assets": len(assets),
        "full_layers": variants[0]["layer_count"],
        "simple_layers": variants[1]["layer_count"],
        "matching_layers": manifest["comparison"]["matching_layer_instances"],
        "full_only": manifest["comparison"]["full_only_layer_ids"],
    }, indent=2))


if __name__ == "__main__":
    main()
