from __future__ import annotations
from dataclasses import dataclass

@dataclass
class Inputs:
    width: float
    height: float
    layers: int
    panel_boards: int
    direct_pth_holes: int
    material: str
    finish: str
    film_cost: float
    etching_cost: float
    masking_cost: float
    silkscreen_cost: float
    sewage_water: float
    sewage_electricity: float
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
    finish_costs: dict
    overheads_pct: float
    yield_baseline_pct: float
    risk_buffer_pct: float
    customer_discount_pct: float
    target_margin_pct: float
    lead_time_mult: dict

def _yield_penalty(inp: Inputs) -> float:
    penalty = 1.0
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
    yld = (prm.yield_baseline_pct / 100.0) * _yield_penalty(inp)
    boards_per_panel = max(1, inp.panel_boards)

    ops = _derive_ops(inp, area_board_cm2)

    # Material cost
    laminate_cost = prm.material_prices.get(inp.material, 15.0)
    finish_cost = prm.finish_costs.get(inp.finish, 0.0)
    film_cost = inp.film_cost
    etching_cost = inp.etching_cost
    masking_cost = inp.masking_cost
    silkscreen_cost = inp.silkscreen_cost
    material_cost = laminate_cost + film_cost
    treatment_cost = finish_cost + etching_cost + masking_cost + silkscreen_cost

    # Process cost
    mr = prm.machine_rates
    drill_cost = mr["drill_per_hit"] * ops["drill_hits"]
    image_cost = mr["imaging_per_pass"] * ops["imaging_passes"]
    lam_cost = mr["lamination"] * ops["lam_cycles"]
    routing_cost = mr["routing_per_mm"] * ops["route_mm"]
    direct_pth_cost = mr.get("direct_pth_per_hole", 0.0) * max(0, inp.direct_pth_holes) * boards_per_panel
    process_cost = drill_cost + image_cost + lam_cost + routing_cost + direct_pth_cost

    # Sewage cost
    sewage_water = inp.sewage_water
    sewage_electricity = inp.sewage_electricity
    sewage_cost = sewage_water + sewage_electricity

    # QA cost
    aoi_cost = mr["aoi_per_panel"]
    if inp.etest == "flying_probe":
        etest_cost = prm.labor_rates["test"] * 0.15
    elif inp.etest == "fixture":
        etest_cost = prm.labor_rates["test"] * 0.30
    else:
        etest_cost = 0.0
    qa_cost = aoi_cost + etest_cost

    base = material_cost + treatment_cost + process_cost + sewage_cost + qa_cost
    oh = base * (prm.overheads_pct / 100.0)

    risk_base = base if (inp.via_type != "thru" or inp.ipc_class == "3") else 0.0
    risk = risk_base * (prm.risk_buffer_pct / 100.0)

    mult = prm.lead_time_mult.get(inp.lead_time_class, 1.0)
    cogs = mult * base + oh + risk
    price_total = cogs * (1 + prm.target_margin_pct / 100.0)
    price_total *= (1 - prm.customer_discount_pct / 100.0)
    unit_price_board = price_total / boards_per_panel if boards_per_panel else 0.0

    breakdown = {
        "material": {
            "total": round(material_cost, 2),
            "components": {
                "laminate": round(laminate_cost, 2),
                "film": round(film_cost, 2),
            }
        },
        "treatment": {
            "total": round(treatment_cost, 2),
            "components": {
                "finish": round(finish_cost, 2),
                "etching": round(etching_cost, 2),
                "masking": round(masking_cost, 2),
                "silkscreen": round(silkscreen_cost, 2)
            }
        },
        "process": {
            "total": round(process_cost, 1),
            "components": {
                "drill": round(drill_cost, 1),
                "imaging": round(image_cost, 1),
                "lamination": round(lam_cost, 1),
                "direct_pth": round(direct_pth_cost, 1),
                "routing": round(routing_cost, 1)
            }
        },
        "sewage": {
            "total": round(sewage_cost, 2),
            "components": {
                "water": round(sewage_water, 2),
                "electricity": round(sewage_electricity, 2)
            }
        },
        "qa": {
            "total": round(qa_cost, 2),
            "components": {
                "aoi": round(aoi_cost, 2),
                "etest": round(etest_cost, 2)
            }
        },
        "overhead": round(oh, 2),
        "risk": round(risk, 2),
        "boards_per_panel": boards_per_panel,
        "yield_pct_effective": round(yld * 100.0, 2)
    }
    return {
        "cogs": round(cogs, 2),
        "price_total": round(price_total, 2),
        "unit_price_board": round(unit_price_board, 4),
        "breakdown": breakdown
    }
