from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


STYLE_NUMBER = re.compile(r"(-?\d+(?:\.\d+)?)\s*(px|%)?")


def parse_style(value: str) -> dict[str, str]:
    result = {}
    for declaration in value.split(";"):
        if ":" not in declaration:
            continue
        key, raw = declaration.split(":", 1)
        result[key.strip().lower()] = raw.strip()
    return result


class LayoutInspector(HTMLParser):
    def __init__(self, limit: int = 20000):
        super().__init__(convert_charrefs=True)
        self.limit = limit
        self.tags = Counter()
        self.elements = []
        self.images = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        self.tags[tag] += 1
        if tag == "img" and values.get("src"):
            self.images.append(values["src"])
        style = parse_style(values.get("style", ""))
        keys = ("position", "left", "top", "width", "height", "z-index", "background-image")
        geometry = {key: style[key] for key in keys if key in style}
        if geometry and len(self.elements) < self.limit:
            self.elements.append({
                "tag": tag,
                "id": values.get("id", ""),
                "class": values.get("class", ""),
                "geometry": geometry,
            })

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def inspect(path: Path, limit: int = 20000) -> dict:
    parser = LayoutInspector(limit)
    # Stream the export in chunks so a large PSD-to-HTML file is never
    # duplicated as one giant in-memory string.
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        while chunk := handle.read(1024 * 1024):
            parser.feed(chunk)
    return {
        "source": str(path),
        "bytes": path.stat().st_size,
        "tag_counts": dict(parser.tags),
        "elements_with_positioning": len(parser.elements),
        "elements": parser.elements,
        "image_count": len(parser.images),
        "images": parser.images[:500],
        "note": "Use this report to author compact layout_profiles.json. Do not load this HTML in the realtime renderer.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a PSD-to-HTML layout export.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=20000)
    args = parser.parse_args()
    report = inspect(args.input, args.limit)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
