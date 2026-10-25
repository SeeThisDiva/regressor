#!/usr/bin/env python3
"""
flamegraph.py
Cross-platform Brendan Gregg-style Differential Flamegraph Generator
Ingests folded stack profiles and outputs an interactive, zoomable vector SVG.
Red = Slower in Candidate (consumed higher % CPU time)
Blue = Faster in Candidate (consumed lower % CPU time)
"""

import argparse
import html
import sys
from collections import defaultdict
from pathlib import Path


def parse_folded(path):
    """Parses a folded stack trace file (frame1;frame2;frame3 <count>)."""
    stacks = {}
    total = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.rsplit(" ", 1)
            if len(parts) == 2:
                stack, count_str = parts
                try:
                    count = int(count_str)
                    stacks[stack] = stacks.get(stack, 0) + count
                    total += count
                except ValueError:
                    continue
    return stacks, total


def compute_leaf_movers(stacks_a, total_a, stacks_b, total_b):
    """Computes self-time deltas grouped by the leaf (innermost) function."""
    leaves_a = defaultdict(int)
    leaves_b = defaultdict(int)

    for stack, count in stacks_a.items():
        leaf = stack.split(";")[-1]
        leaves_a[leaf] += count

    for stack, count in stacks_b.items():
        leaf = stack.split(";")[-1]
        leaves_b[leaf] += count

    all_leaves = set(leaves_a.keys()) | set(leaves_b.keys())
    movers = []

    for leaf in all_leaves:
        pct_a = (leaves_a[leaf] / total_a * 100.0) if total_a > 0 else 0.0
        pct_b = (leaves_b[leaf] / total_b * 100.0) if total_b > 0 else 0.0
        delta = pct_b - pct_a
        movers.append({
            "function": leaf,
            "pct_base": pct_a,
            "pct_cand": pct_b,
            "delta": delta,
        })

    movers.sort(key=lambda x: abs(x["delta"]), reverse=True)
    return movers


def generate_diff_svg(stacks_a, total_a, stacks_b, total_b, title="Differential Flamegraph"):
    """Generates an interactive vector SVG with red/blue differential shading."""
    # Use candidate stacks as layout basis, or combined
    all_stacks = sorted(set(stacks_a.keys()) | set(stacks_b.keys()))
    
    # Calculate stack hierarchy
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

    # Flatten hierarchy into SVG boxes
    svg_width = 1200
    svg_box_height = 18
    max_depth = 0

    boxes = []

    def layout_node(node, depth, x, width):
        nonlocal max_depth
        if depth > max_depth:
            max_depth = depth

        pct_a = (node["base_samples"] / total_a * 100.0) if total_a > 0 else 0.0
        pct_b = (node["cand_samples"] / total_b * 100.0) if total_b > 0 else 0.0
        delta = pct_b - pct_a

        if depth > 0 and width >= 1.0:
            # Determine color: red for slower (delta > 0), blue for faster (delta < 0)
            if abs(delta) < 0.1:
                color = "#e2e8f0" # neutral slate/gray
                text_color = "#334155"
            elif delta > 0:
                intensity = min(int(160 + abs(delta) * 15), 245)
                color = f"rgb({intensity}, 50, 50)"
                text_color = "#ffffff"
            else:
                intensity = min(int(160 + abs(delta) * 15), 245)
                color = f"rgb(50, 80, {intensity})"
                text_color = "#ffffff"

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
        for child_name, child_node in sorted(node["children"].items(), key=lambda c: c[1]["cand_samples"], reverse=True):
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
        Red = Slower in Candidate (&Delta; &gt; 0) | Blue = Faster in Candidate (&Delta; &lt; 0) | Neutral = Unchanged
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

    print(f"\n[perf-guard flamegraph] Parsing profiles:")
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
    out_file.write_text(svg_content, encoding="utf-8")
    print(f"[perf-guard flamegraph] Differential SVG generated ({num_boxes} frames): {out_file.resolve()}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
