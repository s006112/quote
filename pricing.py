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
    ship_zone: str

@dataclass
class Params:
    machine_rates: dict
    material_prices: dict
    finish_costs: dict
    overheads_pct: float
    yield_pct: float
    margin_pct: float
    ship_zone_factor: dict

def price_quote(inp: Inputs, prm: Params) -> dict:
    
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

    # Other cost
    oh = base * max(prm.overheads_pct, 0.0) / 100.0

    yld = base * (100.0 - (yield_pct := min(max(prm.yield_pct, 0.0), 100.0))) / 100.0

    cogs_pre_logistics = base + oh + yld

    zone_factor = prm.ship_zone_factor.get(inp.ship_zone, 1.0)
    logistics_multiplier = max(zone_factor - 1.0, 0.0)
    logistics_cost = cogs_pre_logistics * logistics_multiplier

    other_cost = logistics_cost + oh + yld

    # Total
    cogs = cogs_pre_logistics + logistics_cost

    cogs_unit = cogs / boards_per_panel if boards_per_panel else 0.0
    price_unit = cogs_unit * (1 + prm.margin_pct / 100.0)
    
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
        "others": {
            "total": round(other_cost, 2),
            "ship_zone": inp.ship_zone,
            "factor": round(zone_factor, 3),
            "logistic": round(logistics_cost, 2),
            "overhead": round(oh, 2),
            "yield_pct": round(yield_pct, 2)
        },
        
        "boards_per_panel": boards_per_panel
    }
    return {
        "cogs": round(cogs, 2),
        "cogs_unit": round(cogs_unit, 4),
        "price_unit": round(price_unit, 4),
        "breakdown": breakdown
    }
