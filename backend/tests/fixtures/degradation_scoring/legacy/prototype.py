"""
C4 Severity Ranking Prototype — J26-SE-332
==========================================
Multi-dimensional severity model for architecture-degradation events.

Proves feasibility of:
  - Real blast-radius computation from a dependency graph (NetworkX)
  - Multi-criteria fusion via TOPSIS
  - Ranked output with per-dimension breakdown

Run:  python prototype.py
Out:  severity_report.html  (open in browser)
      severity_results.json (raw data)

Requires: pip install networkx numpy
"""

import networkx as nx
import numpy as np
import json
import html


# ═══════════════════════════════════════════════════════════════════
# 1. BUILD THE DEPENDENCY GRAPH
#    Maps to: Implementation Plan §6.1, Figure 5
#    Each node = architectural module. Each edge = "A depends on B."
# ═══════════════════════════════════════════════════════════════════

G = nx.DiGraph()

# Core layer
G.add_edge("api-gateway",       "auth-service")
G.add_edge("api-gateway",       "core-engine")
G.add_edge("api-gateway",       "config-manager")
G.add_edge("auth-service",      "core-engine")
G.add_edge("auth-service",      "user-store")
G.add_edge("core-engine",       "data-access")
G.add_edge("core-engine",       "event-bus")
G.add_edge("core-engine",       "config-manager")

# Business services
G.add_edge("order-service",     "core-engine")
G.add_edge("order-service",     "payment-service")
G.add_edge("order-service",     "inventory-service")
G.add_edge("payment-service",   "core-engine")
G.add_edge("payment-service",   "data-access")
G.add_edge("inventory-service", "data-access")
G.add_edge("inventory-service", "event-bus")
G.add_edge("notification-svc",  "event-bus")
G.add_edge("notification-svc",  "user-store")
G.add_edge("reporting-svc",     "data-access")
G.add_edge("reporting-svc",     "core-engine")
G.add_edge("scheduler",         "core-engine")
G.add_edge("scheduler",         "event-bus")

# Shared infrastructure
G.add_edge("data-access",       "config-manager")
G.add_edge("event-bus",         "config-manager")
G.add_edge("user-store",        "data-access")

print(f"Graph: {G.number_of_nodes()} modules, {G.number_of_edges()} dependencies")


# ═══════════════════════════════════════════════════════════════════
# 2. DEGRADATION EVENTS (dummy C3 output)
#    Maps to: Implementation Plan §4.1 (event contract)
#    blast_radius = computed LIVE.  Others = hardcoded stubs.
# ═══════════════════════════════════════════════════════════════════

events = [
    {
        "id": "EVT-001",
        "type": "Hub-like dependency",
        "description": "core-engine has excessive incoming dependencies",
        "elements": ["core-engine"],
        "hotspot_churn": 142,
        "hotspot_authors": 8,
        "adr_violation": 0.9,
        "persistence_releases": 5,
    },
    {
        "id": "EVT-002",
        "type": "Cyclic dependency",
        "description": "payment-service and core-engine form a cycle",
        "elements": ["payment-service", "core-engine"],
        "hotspot_churn": 98,
        "hotspot_authors": 5,
        "adr_violation": 1.0,
        "persistence_releases": 4,
    },
    {
        "id": "EVT-003",
        "type": "Layering violation",
        "description": "reporting-svc bypasses core-engine to access data-access directly",
        "elements": ["reporting-svc"],
        "hotspot_churn": 23,
        "hotspot_authors": 2,
        "adr_violation": 0.7,
        "persistence_releases": 6,
    },
    {
        "id": "EVT-004",
        "type": "Feature concentration",
        "description": "data-access has grown into a god module",
        "elements": ["data-access"],
        "hotspot_churn": 167,
        "hotspot_authors": 11,
        "adr_violation": 0.3,
        "persistence_releases": 3,
    },
    {
        "id": "EVT-005",
        "type": "Unused interface",
        "description": "config-manager exposes 12 endpoints, only 3 are used",
        "elements": ["config-manager"],
        "hotspot_churn": 11,
        "hotspot_authors": 1,
        "adr_violation": 0.0,
        "persistence_releases": 7,
    },
    {
        "id": "EVT-006",
        "type": "Scattered functionality",
        "description": "notification-svc duplicates logic found in event-bus",
        "elements": ["notification-svc", "event-bus"],
        "hotspot_churn": 56,
        "hotspot_authors": 3,
        "adr_violation": 0.5,
        "persistence_releases": 2,
    },
]


# ═══════════════════════════════════════════════════════════════════
# 3. BLAST-RADIUS COMPUTATION (LIVE — the primary feasibility proof)
#    Maps to: Implementation Plan §6.1, Figure 5
# ═══════════════════════════════════════════════════════════════════

# Compute graph-wide metrics once (cached per release in the real system)
pagerank    = nx.pagerank(G, weight=None)
betweenness = nx.betweenness_centrality(G)
total_nodes = G.number_of_nodes()


def compute_blast_radius(graph, element_nodes):
    """
    Compute structural blast-radius features for architectural elements.

    Returns:
      fan_in_ratio  — fraction of system that transitively depends on these elements
      pagerank_sum  — sum of PageRank scores (importance via indirect dependency)
      betweenness   — max betweenness centrality (bridge-ness)
      depth         — max dependency depth from any root
    """
    # Transitive dependents (ancestors in a directed graph)
    ancestors = set()
    for node in element_nodes:
        if node in graph:
            ancestors |= nx.ancestors(graph, node)
    ancestors -= set(element_nodes)

    fan_in_ratio = len(ancestors) / max(total_nodes - len(element_nodes), 1)

    # PageRank: sum across all elements in this event
    pr_sum = sum(pagerank.get(n, 0) for n in element_nodes)

    # Betweenness: highest among elements
    btw_max = max((betweenness.get(n, 0) for n in element_nodes), default=0)

    # Depth: longest path from any root to any element
    roots = [n for n in graph.nodes() if graph.in_degree(n) == 0]
    max_depth = 0
    for root in roots:
        for node in element_nodes:
            if node in graph and nx.has_path(graph, root, node):
                d = nx.shortest_path_length(graph, root, node)
                max_depth = max(max_depth, d)

    return {
        "fan_in_ratio": round(fan_in_ratio, 4),
        "pagerank_sum": round(pr_sum, 4),
        "betweenness":  round(btw_max, 4),
        "depth":        max_depth,
    }


# Compute blast radius for every event
for evt in events:
    evt["blast_radius"] = compute_blast_radius(G, evt["elements"])

print("\n── Blast-radius features (computed live from graph) ──")
for evt in events:
    br = evt["blast_radius"]
    print(f"  {evt['id']}: fan-in={br['fan_in_ratio']:.2%}  "
          f"PR={br['pagerank_sum']:.4f}  "
          f"btw={br['betweenness']:.4f}  "
          f"depth={br['depth']}")


# ═══════════════════════════════════════════════════════════════════
# 4. BUILD FEATURE MATRIX AND NORMALISE
#    Maps to: Implementation Plan §5.2
# ═══════════════════════════════════════════════════════════════════

def aggregate_blast_radius(br):
    """Combine four BR features into one 0-1 score."""
    return (0.40 * br["fan_in_ratio"]
          + 0.30 * min(br["pagerank_sum"] * 10, 1.0)
          + 0.20 * br["betweenness"]
          + 0.10 * min(br["depth"] / 5, 1.0))


# Build raw decision matrix: [blast_radius, hotspot, adr_violation, persistence]
raw_matrix = []
for evt in events:
    br_score = aggregate_blast_radius(evt["blast_radius"])
    hotspot  = evt["hotspot_churn"] * 0.7 + evt["hotspot_authors"] * 3.0
    adr_viol = evt["adr_violation"]
    persist  = evt["persistence_releases"]
    raw_matrix.append([br_score, hotspot, adr_viol, persist])

raw_matrix = np.array(raw_matrix)


def normalize_minmax(matrix):
    """Min-max normalise each column to [0, 1]."""
    mins   = matrix.min(axis=0)
    maxs   = matrix.max(axis=0)
    ranges = maxs - mins
    ranges[ranges == 0] = 1
    return (matrix - mins) / ranges


norm_matrix = normalize_minmax(raw_matrix)

criteria = ["BlastRadius", "Hotspot", "ADR_Viol", "Persistence"]
print("\n── Normalised decision matrix ──")
print(f"  {'Event':>8}  " + "  ".join(f"{c:>12}" for c in criteria))
for i, evt in enumerate(events):
    vals = "  ".join(f"{norm_matrix[i,j]:12.3f}" for j in range(4))
    print(f"  {evt['id']:>8}  {vals}")


# ═══════════════════════════════════════════════════════════════════
# 5. TOPSIS RANKING
#    Maps to: Implementation Plan §5.2 (the core formula)
# ═══════════════════════════════════════════════════════════════════

# Weights (real system: AHP with consistency ratio check)
weights = np.array([0.40, 0.30, 0.15, 0.15])


def topsis(matrix, w):
    """
    TOPSIS: Technique for Order Preference by Similarity to Ideal Solution.

    1. Vector-normalise  2. Weight  3. Ideals  4. Distance  5. Closeness
    """
    # Step 1: vector normalisation
    norms = np.sqrt((matrix ** 2).sum(axis=0))
    norms[norms == 0] = 1
    r = matrix / norms

    # Step 2: weighted normalised matrix
    v = r * w

    # Step 3: ideal and anti-ideal
    ideal      = v.max(axis=0)
    anti_ideal = v.min(axis=0)

    # Step 4: distances
    d_ideal      = np.sqrt(((v - ideal) ** 2).sum(axis=1))
    d_anti_ideal = np.sqrt(((v - anti_ideal) ** 2).sum(axis=1))

    # Step 5: closeness coefficient (higher = more severe)
    closeness = d_anti_ideal / (d_ideal + d_anti_ideal + 1e-10)

    return closeness


severity_scores = topsis(norm_matrix, weights)

for i, evt in enumerate(events):
    evt["severity_score"] = round(float(severity_scores[i]), 4)

# Rank descending
ranked = sorted(events, key=lambda e: e["severity_score"], reverse=True)
for rank, evt in enumerate(ranked, 1):
    evt["rank"] = rank

print("\n── TOPSIS severity ranking ──")
for evt in ranked:
    print(f"  #{evt['rank']}  {evt['id']}  severity={evt['severity_score']:.4f}  "
          f"{evt['type']}")


# ═══════════════════════════════════════════════════════════════════
# 6. STUB EXPLANATIONS
#    Maps to: Implementation Plan §6.5 (real system = RAG + audit)
# ═══════════════════════════════════════════════════════════════════

def generate_stub_explanation(evt):
    """Template explanation showing the OUTPUT SHAPE of a grounded explanation."""
    br = evt["blast_radius"]
    parts = [
        f"This {evt['type'].lower()} event affecting "
        f"{', '.join(evt['elements'])} ranks #{evt['rank']} in severity "
        f"(score: {evt['severity_score']:.3f}).",

        f"Structural impact: {br['fan_in_ratio']:.0%} of the system "
        f"transitively depends on the affected element(s) "
        f"(PageRank: {br['pagerank_sum']:.4f}, "
        f"betweenness: {br['betweenness']:.4f}).",

        f"Evolutionary activity: {evt['hotspot_churn']} lines changed "
        f"by {evt['hotspot_authors']} authors in recent releases.",
    ]
    if evt["adr_violation"] > 0:
        parts.append(
            f"This event contradicts a documented architectural decision "
            f"(violation confidence: {evt['adr_violation']:.0%}).")
    parts.append(
        f"The issue has persisted across {evt['persistence_releases']} "
        f"consecutive releases, indicating a worsening trend.")
    return " ".join(parts)


for evt in ranked:
    evt["explanation"] = generate_stub_explanation(evt)


# ═══════════════════════════════════════════════════════════════════
# 7. RENDER HTML REPORT
#    Maps to: Implementation Plan §4.2 (output format)
# ═══════════════════════════════════════════════════════════════════

def severity_bar(score):
    pct = score * 100
    if pct >= 70:   color = "#A3162B"
    elif pct >= 45: color = "#C47A15"
    elif pct >= 25: color = "#8C6A12"
    else:           color = "#4A5763"
    return (f'<div style="display:flex;align-items:center;gap:8px">'
            f'<div style="width:{pct:.0f}%;height:8px;background:{color};'
            f'border-radius:4px;min-width:4px"></div>'
            f'<span style="font-size:13px;font-weight:600;color:{color}">'
            f'{score:.3f}</span></div>')


def dim_pill(label, raw_val, norm_val, weight):
    return (f'<span style="display:inline-block;background:#EEF1EE;'
            f'border:1px solid #CBD3CD;border-radius:4px;padding:2px 8px;'
            f'margin:2px 4px 2px 0;font-size:11px;font-family:Archivo,sans-serif">'
            f'{label}: <b>{raw_val}</b> '
            f'(norm: {norm_val:.2f}, w={weight})</span>')


report_rows = []
for evt in ranked:
    br = evt["blast_radius"]
    # Find this event's index in the original list for norm_matrix lookup
    idx = next(i for i, e in enumerate(events) if e["id"] == evt["id"])
    nv = norm_matrix[idx]

    dims = (
        dim_pill("Blast Radius", f"{br['fan_in_ratio']:.0%} fan-in", nv[0], "0.40")
        + dim_pill("Hotspot", f"{evt['hotspot_churn']} churn", nv[1], "0.30")
        + dim_pill("ADR Viol.", f"{evt['adr_violation']:.0%}", nv[2], "0.15")
        + dim_pill("Persistence", f"{evt['persistence_releases']}r", nv[3], "0.15")
    )

    report_rows.append(f"""
    <tr>
      <td style="text-align:center;font-weight:700;font-size:22px;color:#1F6F5C">
        #{evt["rank"]}</td>
      <td>
        <div style="font-weight:600;margin-bottom:3px">
          {evt["id"]} — {evt["type"]}</div>
        <div style="font-size:13px;color:#3A4B58;margin-bottom:6px">
          {html.escape(evt["description"])}</div>
        <div style="margin-bottom:6px">{dims}</div>
        {severity_bar(evt["severity_score"])}
      </td>
      <td style="font-size:13px;line-height:1.5;color:#3A4B58">
        {html.escape(evt["explanation"])}</td>
    </tr>""")


report_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>C4 Prototype — Severity Ranking Report</title>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;700&display=swap"
      rel="stylesheet">
<style>
  body {{ font-family: Archivo, sans-serif; margin: 40px auto; max-width: 1100px;
         padding: 0 24px; background: #F6F7F5; color: #12212B }}
  .hdr {{ border-top: 4px solid #12212B; padding-top: 16px; margin-bottom: 28px }}
  .hdr h1 {{ font-size: 28px; margin: 8px 0 4px }}
  .hdr p {{ color: #3A4B58; font-size: 15px; margin: 0 }}
  .badge {{ display: inline-block; font-size: 10px; font-weight: 600;
            letter-spacing: .1em; text-transform: uppercase; padding: 2px 8px;
            border-radius: 99px; margin-right: 6px }}
  .badge.live {{ background: #EAF3EF; border: 1px solid #1F6F5C; color: #1F6F5C }}
  .badge.stub {{ background: #FFF8E7; border: 1px solid #8C6A12; color: #8C6A12 }}
  table {{ border-collapse: collapse; width: 100%; background: #fff;
           border: 1px solid #CBD3CD }}
  th {{ background: #12212B; color: #fff; padding: 10px 14px; text-align: left;
       font-size: 11px; letter-spacing: .08em; text-transform: uppercase }}
  td {{ padding: 14px; border-top: 1px solid #E4E8E4; vertical-align: top }}
  tbody tr:nth-child(even) {{ background: #FAFBFA }}
  .foot {{ margin-top: 20px; font-size: 12px; color: #4A5763;
           border-top: 1px solid #CBD3CD; padding-top: 12px }}
</style>
</head>
<body>
<div class="hdr">
  <div style="font-size:11px;font-weight:600;letter-spacing:.18em;
              text-transform:uppercase;color:#A3162B">
    C4 Prototype · J26-SE-332</div>
  <h1>Architecture Degradation — Severity Ranking</h1>
  <p>Multi-dimensional severity model: blast radius (live graph computation)
     + evolutionary hotspot + ADR violation + persistence → TOPSIS ranking</p>
  <div style="margin-top:10px">
    <span class="badge live">Blast radius — computed live</span>
    <span class="badge stub">Hotspot — stubbed</span>
    <span class="badge stub">ADR violation — stubbed</span>
    <span class="badge stub">Persistence — stubbed</span>
    <span class="badge stub">Explanation — template</span>
  </div>
</div>

<table>
<thead><tr>
  <th style="width:60px">Rank</th>
  <th style="width:48%">Event &amp; Dimensions</th>
  <th>Explanation</th>
</tr></thead>
<tbody>
  {"".join(report_rows)}
</tbody>
</table>

<div class="foot">
  <b>Prototype note:</b> Blast-radius features computed live via NetworkX
  (PageRank, betweenness centrality, transitive fan-in) on a
  {G.number_of_nodes()}-module dependency graph.
  Hotspot, ADR violation, and persistence values are hardcoded stubs.
  TOPSIS weights: BR=0.40, EH=0.30, AV=0.15, PS=0.15.
  Full system: PyDriller for hotspots, C2 ADR index for violations,
  RefactoringMiner for ground-truth validation,
  RAG + faithfulness audit for explanations.
</div>
</body></html>"""

# Write the HTML report
with open("severity_report.html", "w", encoding="utf-8") as f:
    f.write(report_html)

# Write raw JSON results
output_json = []
for evt in ranked:
    output_json.append({
        "rank":         evt["rank"],
        "event_id":     evt["id"],
        "type":         evt["type"],
        "severity":     evt["severity_score"],
        "blast_radius": evt["blast_radius"],
        "dimensions": {
            "hotspot_churn":      evt["hotspot_churn"],
            "hotspot_authors":    evt["hotspot_authors"],
            "adr_violation":      evt["adr_violation"],
            "persistence":        evt["persistence_releases"],
        },
        "explanation":  evt["explanation"],
    })

with open("severity_results.json", "w", encoding="utf-8") as f:
    json.dump(output_json, f, indent=2)

print(f"\n{'='*60}")
print(f"  ✓ severity_report.html  — open in browser")
print(f"  ✓ severity_results.json — raw ranked data")
print(f"{'='*60}")