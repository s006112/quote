from __future__ import annotations
import math
from dataclasses import dataclass

@dataclass
class Inputs:
    width: float
    height: float
    layers: int
    qty_tiers: list[int]
    panel_boards: int
    panel_area_cm2: float
    material: str
    thickness_mm: float
    outer_oz: float
    inner_oz: float | None
    finish: str
    min_track_mm: float
    min_space_mm: float
    min_hole_mm: float
    via_type: str  # 'thru'|'blind'|'buried'|'micro'
    ipc_class: str # '2'|'3'
    etest: str     # 'none'|'flying_probe'|'fixture'
    lead_time_class: str # 'economy'|'standard'|'express'
    ship_zone: str

@dataclass
class Params:
    labor_rates: dict
    machine_rates: dict
    material_prices: dict
    overheads_pct: float
    yield_baseline_pct: float
    risk_buffer_pct: float
    customer_discount_pct: float
    target_margin_pct: float
    lead_time_mult: dict
    scarcity_mult: dict

def _tier_discount(q: int) -> float:
    # Simple monotone discount curve
    if q >= 1000: return 0.95
    if q >= 500:  return 0.96
    if q >= 200:  return 0.97
    if q >= 100:  return 0.98
    if q >= 50:   return 0.99
    return 1.00

def _yield_penalty(inp: Inputs) -> float:
    penalty = 1.0
    if inp.min_track_mm < 0.1:      penalty *= 0.97
    if inp.outer_oz >= 2.0:         penalty *= 0.97
    if inp.via_type != "thru":      penalty *= 0.94
    if inp.ipc_class == "3":        penalty *= 0.97
    return penalty

def _derive_ops(inp: Inputs, area_board_cm2: float) -> dict:
    # Heuristic counts; replace with CAM-driven values later
    drill_hits = max(200, int(area_board_cm2 * 6 * (1 if inp.via_type=='thru' else 1.6)))
    layer_pairs = (inp.layers // 2)
    lam_cycles = max(1, layer_pairs)
    imaging_passes = inp.layers * 2
    route_mm = (inp.width*2 + inp.height*2) * 10  # perimeter in mm
    nets = max(300, int(area_board_cm2 * 5))
    bga_count = 0
    return dict(drill_hits=drill_hits, layer_pairs=layer_pairs, lam_cycles=lam_cycles,
                imaging_passes=imaging_passes, route_mm=route_mm, nets=nets, bga_count=bga_count)

def price_quote(inp: Inputs, prm: Params) -> dict:
    area_board_cm2 = (inp.width * inp.height) / 100.0
    boards_needed = sum(inp.qty_tiers)
    yld = (prm.yield_baseline_pct / 100.0) * _yield_penalty(inp)
    boards_per_panel = max(1, inp.panel_boards)
    panels_needed = math.ceil(boards_needed / (boards_per_panel * yld))

    ops = _derive_ops(inp, area_board_cm2)

    # Material cost
    mat_unit = prm.material_prices.get(inp.material, 15.0)
    material_cost = mat_unit * (inp.panel_area_cm2 / 100.0) * panels_needed
    gold_um = 0.1 if inp.finish == "ENIG" else 0.0
    gold_cost = prm.material_prices["ENIG_gold_per_um_cm2"] * gold_um * area_board_cm2 * boards_needed * 0.45
    material_cost += gold_cost

    # Process cost
    mr = prm.machine_rates
    drill_cost = mr["drill_per_hit"] * ops["drill_hits"] * panels_needed
    image_cost = mr["imaging_per_pass"] * ops["imaging_passes"] * panels_needed
    lam_cost = mr["lamination"] * ops["lam_cycles"] * panels_needed
    routing_cost = mr["routing_per_mm"] * ops["route_mm"] * panels_needed
    process_cost = drill_cost + image_cost + lam_cost + routing_cost

    # QA cost
    aoi_cost = mr["aoi_per_panel"] * panels_needed
    if inp.etest == "flying_probe":
        etest_cost = prm.labor_rates["test"] * 0.15 * panels_needed
    elif inp.etest == "fixture":
        etest_cost = prm.labor_rates["test"] * 0.30 * panels_needed
    else:
        etest_cost = 0.0
    qa_cost = aoi_cost + etest_cost

    base = material_cost + process_cost + qa_cost
    oh = base * (prm.overheads_pct / 100.0)

    risk_base = base if (inp.via_type != "thru" or inp.ipc_class == "3") else 0.0
    risk = risk_base * (prm.risk_buffer_pct / 100.0)

    mult = prm.lead_time_mult.get(inp.lead_time_class, 1.0) * prm.scarcity_mult.get(inp.material, 1.0)
    cogs = mult * base + oh + risk

    tiers = {}
    for q in inp.qty_tiers:
        tdisc = _tier_discount(q)
        price = cogs * (1 + prm.target_margin_pct/100.0) * tdisc
        price *= (1 - prm.customer_discount_pct/100.0)
        tiers[q] = {"unit_price": round(price / q, 4), "total": round(price, 2)}

    breakdown = {
        "material": round(material_cost, 2),
        "process": round(process_cost, 2),
        "qa": round(qa_cost, 2),
        "overhead": round(oh, 2),
        "risk": round(risk, 2),
        "panels_needed": panels_needed,
        "yield_pct_effective": round(yld * 100.0, 2)
    }
    return {"cogs": round(cogs, 2), "tiers": tiers, "breakdown": breakdown}
