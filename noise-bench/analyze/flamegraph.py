#!/usr/bin/env python3
"""
Differential flamegraph generator for folded stack profiles.

Ingests baseline and candidate folded stack traces (`frame1;frame2 <count>`)
and outputs an interactive, hoverable SVG where:
  - Red  = hotter in candidate (higher % CPU time)
  - Blue = cooler in candidate (lower % CPU time)
"""

import argparse
import html
import sys
from collections import defaultdict
from pathlib import Path


def _pct_delta(base_samples, total_base, cand_samples, total_cand):
    """Return `(pct_base, pct_cand, delta)` percentages for a stack or frame."""
    pct_base = (base_samples / total_base * 100.0) if total_base > 0 else 0.0
    pct_cand = (cand_samples / total_cand * 100.0) if total_cand > 0 else 0.0
    return pct_base, pct_cand, pct_cand - pct_base


def _delta_colors(delta):
    """Return `(fill_color, text_color)` for a frame percentage delta."""
    if abs(delta) < 0.1:
        return "#e2e8f0", "#334155"
    intensity = min(int(160 + abs(delta) * 15), 245)
    if delta > 0:
        return f"rgb({intensity}, 50, 50)", "#ffffff"
    return f"rgb(50, 80, {intensity})", "#ffffff"


def parse_folded(path):
    """Parse a folded stack trace file (`frame1;frame2;frame3 <count>`)."""
    stacks = {}
    total = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.rsplit(None, 1)
            if len(parts) != 2:
                continue
            stack, count_str = parts
            try:
                count = int(count_str)
            except ValueError:
                continue
            stacks[stack] = stacks.get(stack, 0) + count
            total += count
    return stacks, total


def compute_leaf_movers(stacks_a, total_a, stacks_b, total_b):
    """Compute self-time deltas grouped by leaf (innermost) function."""
    leaves_a = defaultdict(int)
    leaves_b = defaultdict(int)

    for stack, count in stacks_a.items():
        leaves_a[stack.split(";")[-1]] += count

    for stack, count in stacks_b.items():
        leaves_b[stack.split(";")[-1]] += count

    movers = []
    for leaf in set(leaves_a) | set(leaves_b):
        pct_a, pct_b, delta = _pct_delta(leaves_a[leaf], total_a, leaves_b[leaf], total_b)
        movers.append({
            "function": leaf,
            "pct_base": pct_a,
            "pct_cand": pct_b,
            "delta": delta,
        })

    movers.sort(key=lambda x: abs(x["delta"]), reverse=True)
    return movers


def generate_diff_svg(stacks_a, total_a, stacks_b, total_b, title="Differential Flamegraph"):
    """Generate an interactive differential SVG with red/blue frame shading."""
    all_stacks = sorted(set(stacks_a) | set(stacks_b))
    tree = {"name": "root", "children": {}, "base_samples": 0, "cand_samples": 0}

    for stack in all_stacks:
        frames = stack.split(";")
        cnt_a = stacks_a.get(stack, 0)
        cnt_b = stacks_b.get(stack, 0)

        curr = tree
        curr["base_samples"] += cnt_a
        curr["cand_samples"] += cnt_b

        for frame in frames:
            if frame not in curr["children"]:
                curr["children"][frame] = {
                    "name": frame,
                    "children": {},
                    "base_samples": 0,
                    "cand_samples": 0,
                }
            curr = curr["children"][frame]
            curr["base_samples"] += cnt_a
            curr["cand_samples"] += cnt_b

    svg_width = 1200
    svg_box_height = 18
    max_depth = 0
    boxes = []

    def layout_node(node, depth, x, width):
        nonlocal max_depth
        if depth > max_depth:
            max_depth = depth

        pct_a, pct_b, delta = _pct_delta(
            node["base_samples"], total_a, node["cand_samples"], total_cand=total_b
        )

        if depth > 0 and width >= 1.0:
            color, text_color = _delta_colors(delta)
            boxes.append({
                "name": node["name"],
                "depth": depth,
                "x": x,
                "width": width,
                "pct_base": pct_a,
                "pct_cand": pct_b,
                "delta": delta,
                "color": color,
                "text_color": text_color,
            })

        curr_x = x
        children = sorted(node["children"].values(), key=lambda c: c["cand_samples"], reverse=True)
        for child_node in children:
            child_weight = (child_node["cand_samples"] / node["cand_samples"]) if node["cand_samples"] > 0 else 0
            child_w = width * child_weight
            if child_w >= 0.5:
                layout_node(child_node, depth + 1, curr_x, child_w)
                curr_x += child_w

    layout_node(tree, 0, 10, svg_width - 20)

    svg_height = (max_depth + 3) * svg_box_height + 80
    box_elements = []

    for b in boxes:
        y = svg_height - 50 - (b["depth"] * svg_box_height)
        max_chars = max(0, int((b["width"] - 8) // 6))
        raw_label = b["name"][:max_chars] if b["width"] > 40 and max_chars > 0 else ""
        label = html.escape(raw_label)
        safe_name = html.escape(b["name"], quote=True)
        tooltip = f"{safe_name} | Base: {b['pct_base']:.2f}% | Cand: {b['pct_cand']:.2f}% | Δ: {b['delta']:+.2f}%"

        box_elements.append(f"""
        <g class="func" data-info="{tooltip}">
            <rect x="{b['x']:.1f}" y="{y:.1f}" width="{b['width']:.1f}" height="{svg_box_height - 2}" rx="2" fill="{b['color']}" stroke="#ffffff" stroke-width="0.5"/>
            <text x="{b['x'] + 4:.1f}" y="{y + 12:.1f}" fill="{b['text_color']}" font-size="10" font-family="monospace">{label}</text>
        </g>
        """)

    safe_title = html.escape(title)
    svg_content = f"""<svg version="1.1" width="100%" height="{svg_height}" viewBox="0 0 {svg_width} {svg_height}" xmlns="http://www.w3.org/2000/svg" style="background:#f8fafc;">
    <style>
        .func:hover rect {{ stroke: #000000; stroke-width: 1.5; cursor: pointer; }}
        text {{ user-select: none; pointer-events: none; }}
    </style>
    <!-- Header -->
    <text x="10" y="25" font-family="sans-serif" font-size="16" font-weight="bold" fill="#0f172a">{safe_title}</text>
    <text x="10" y="42" font-family="sans-serif" font-size="11" fill="#64748b">
        Red = Slower in Candidate (&#916; &gt; 0) | Blue = Faster in Candidate (&#916; &lt; 0) | Neutral = Unchanged
    </text>

    <!-- Legend -->
    <rect x="{svg_width - 220}" y="15" width="14" height="14" fill="rgb(220, 50, 50)" rx="2"/>
    <text x="{svg_width - 200}" y="26" font-family="sans-serif" font-size="11" fill="#334155">Hotter (+% CPU)</text>
    <rect x="{svg_width - 110}" y="15" width="14" height="14" fill="rgb(50, 80, 220)" rx="2"/>
    <text x="{svg_width - 90}" y="26" font-family="sans-serif" font-size="11" fill="#334155">Cooler (-% CPU)</text>

    <!-- Flamegraph Boxes -->
    <g id="boxes">
        {"".join(box_elements)}
    </g>

    <!-- Dynamic Status Bar -->
    <rect x="0" y="{svg_height - 25}" width="{svg_width}" height="25" fill="#0f172a"/>
    <text id="status" x="10" y="{svg_height - 8}" font-family="monospace" font-size="11" fill="#f8fafc">Hover over any frame to inspect stack percentage and delta</text>

    <script><![CDATA[
        "use strict";
        function get_params() {{
            var params = Object.create(null);
            var paramsarr = window.location.search.substr(1).split('&');
            for (var i = 0; i < paramsarr.length; ++i) {{
                var tmp = paramsarr[i].split("=");
                if (!tmp[0] || !tmp[1]) continue;
                if (tmp[0] === "__proto__" || tmp[0] === "prototype" || tmp[0] === "constructor") continue;
                params[tmp[0]] = decodeURIComponent(tmp[1]);
            }}
            return params;
        }}
        var params = get_params();
        if (params.x && /^[0-9.]+$/.test(params.x)) {{
            var match = document.querySelector('rect[x="' + params.x + '"]');
            if (match && match.parentElement) {{
                document.getElementById('status').textContent = match.parentElement.getAttribute('data-info');
            }}
        }}
        document.querySelectorAll('.func').forEach(el => {{
            el.addEventListener('mouseenter', () => {{
                document.getElementById('status').textContent = el.getAttribute('data-info');
            }});
        }});
    ]]></script>
</svg>
"""
    return svg_content, len(boxes)


def main():
    parser = argparse.ArgumentParser(description="Generate interactive differential flamegraph from folded stack profiles")
    parser.add_argument("baseline_folded", help="Path to baseline folded stack file")
    parser.add_argument("candidate_folded", help="Path to candidate folded stack file")
    parser.add_argument("--title", default="Differential Flamegraph (Hotspot Attribution)", help="SVG chart title")
    parser.add_argument("-o", "--output", default="flamegraph_diff.svg", help="Output SVG file path")
    args = parser.parse_args()

    base_path = Path(args.baseline_folded)
    cand_path = Path(args.candidate_folded)

    if not base_path.exists():
        print(f"Error: Baseline profile not found: {base_path}", file=sys.stderr)
        return 1
    if not cand_path.exists():
        print(f"Error: Candidate profile not found: {cand_path}", file=sys.stderr)
        return 1

    stacks_a, total_a = parse_folded(base_path)
    stacks_b, total_b = parse_folded(cand_path)

    print("\n[flamegraph] Parsing profiles:")
    print(f"  Baseline:  {base_path.name} ({total_a:,} total samples, {len(stacks_a):,} unique stacks)")
    print(f"  Candidate: {cand_path.name} ({total_b:,} total samples, {len(stacks_b):,} unique stacks)\n")

    movers = compute_leaf_movers(stacks_a, total_a, stacks_b, total_b)

    print("=" * 80)
    print("  TOP LEAF FUNCTION MOVERS (Self-Time Shift)")
    print("=" * 80)
    print(f"  {'Function':45s} | {'Base %':8s} | {'Cand %':8s} | {'Delta':8s} | Status")
    print("-" * 80)

    for m in movers[:10]:
        delta_str = f"{m['delta']:+.2f}%"
        status = "HOTSPOT" if m["delta"] > 1.0 else ("FASTER" if m["delta"] < -1.0 else "NEGLIGIBLE")
        print(f"  {m['function'][:45]:45s} | {m['pct_base']:7.2f}% | {m['pct_cand']:7.2f}% | {delta_str:8s} | {status}")
    print("=" * 80 + "\n")

    svg_content, num_boxes = generate_diff_svg(stacks_a, total_a, stacks_b, total_b, title=args.title)
    out_file = Path(args.output)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(svg_content, encoding="utf-8")
    print(f"[flamegraph] Differential SVG generated ({num_boxes} frames): {out_file.resolve()}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
