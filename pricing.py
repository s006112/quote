from __future__ import annotations
from dataclasses import dataclass

@dataclass
class Inputs:
    width: float
    height: float
    layers: int
    panel_boards: int
    direct_pth_holes: int
    cnc_pth_holes: int
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

def price_quote(inp: Inputs, prm: Params) -> dict:
    yld = (prm.yield_baseline_pct / 100.0) * _yield_penalty(inp)
    boards_per_panel = max(1, inp.panel_boards)

    # Material cost
    laminate_cost = prm.material_prices.get(inp.material, 15.0)
    film_cost = inp.film_cost
    material_cost = laminate_cost + film_cost

    # Treatment cost
    etching_cost = inp.etching_cost
    masking_cost = inp.masking_cost
    silkscreen_cost = inp.silkscreen_cost
    finish_cost = prm.finish_costs.get(inp.finish, 0.0)
    treatment_cost = finish_cost + etching_cost + masking_cost + silkscreen_cost

    # Process cost
    mr = prm.machine_rates
    direct_pth_cost = mr.get("direct_pth_per_hole", 0.0) * max(0, inp.direct_pth_holes) * boards_per_panel
    cnc_pth_cost = mr.get("cnc_pth_per_hole", 0.0) * max(0, inp.cnc_pth_holes) * boards_per_panel
    process_cost = direct_pth_cost + cnc_pth_cost

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
                "direct_pth": round(direct_pth_cost, 1),
                "cnc_pth": round(cnc_pth_cost, 1)
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
