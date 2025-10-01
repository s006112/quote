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
    cutting_cost: float
    routing_cost: float
    e_test_cost: float
    v_cut_cost: float
    fqc_cost: float
    package_cost: float
    sewage_water: float
    sewage_electricity: float
    via_type: str  # 'thru'|'blind'|'buried'|'micro'
    ship_zone: str

@dataclass
class Params:
    machine_rates: dict
    material_prices: dict
    finish_costs: dict
    overheads_pct: float
    yield_baseline_pct: float
    risk_buffer_pct: float
    customer_discount_pct: float
    target_margin_pct: float
    ship_zone_factor: dict

def _yield_penalty(inp: Inputs) -> float:
    penalty = 1.0
    if inp.via_type != "thru":      penalty *= 0.94
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
    cutting_cost = max(0.0, inp.cutting_cost)
    routing_cost = max(0.0, inp.routing_cost)
    e_test_cost = max(0.0, inp.e_test_cost)
    v_cut_cost = max(0.0, inp.v_cut_cost)
    fqc_cost = max(0.0, inp.fqc_cost)
    package_cost = max(0.0, inp.package_cost)
    process_cost = (
        direct_pth_cost +
        cnc_pth_cost +
        cutting_cost +
        routing_cost +
        e_test_cost +
        v_cut_cost +
        fqc_cost +
        package_cost
    )

    # Sewage cost
    sewage_water = inp.sewage_water
    sewage_electricity = inp.sewage_electricity
    sewage_cost = sewage_water + sewage_electricity

    base = material_cost + treatment_cost + process_cost + sewage_cost
    oh = base * (prm.overheads_pct / 100.0)

    risk_base = base if inp.via_type != "thru" else 0.0
    risk = risk_base * (prm.risk_buffer_pct / 100.0)

    cogs_pre_ship = base + oh + risk
    zone_factor = prm.ship_zone_factor.get(inp.ship_zone, 1.0)
    logistics_cost = cogs_pre_ship * (zone_factor - 1)
    cogs = cogs_pre_ship + logistics_cost

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
                "cnc_pth": round(cnc_pth_cost, 1),
                "cutting": round(cutting_cost, 1),
                "routing": round(routing_cost, 1),
                "e_test": round(e_test_cost, 1),
                "v_cut": round(v_cut_cost, 1),
                "fqc": round(fqc_cost, 1),
                "package": round(package_cost, 1)
            }
        },
        "sewage": {
            "total": round(sewage_cost, 2),
            "components": {
                "water": round(sewage_water, 2),
                "electricity": round(sewage_electricity, 2)
            }
        },
        "logistics": {
            "ship_zone": inp.ship_zone,
            "factor": round(zone_factor, 3),
            "adjustment": round(logistics_cost, 2)
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
