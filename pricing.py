from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping

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

def _non_negative(value: float) -> float:
    return max(value, 0.0)

def _percent(value: float) -> float:
    return max(0.0, min(100.0, value))

def _component_total(components: Mapping[str, float]) -> float:
    return sum(components.values())

def _rounded(components: Mapping[str, float], digits: int) -> dict:
    return {name: round(amount, digits) for name, amount in components.items()}

def price_quote(inp: Inputs, prm: Params) -> dict:

    boards_per_panel = max(1, int(inp.panel_boards) if inp.panel_boards else 1)

    # Material cost
    material_components = {
        "laminate": prm.material_prices.get(inp.material, 15.0),
        "film": inp.film_cost,
    }
    material_cost = _component_total(material_components)

    # Treatment cost
    treatment_components = {
        "finish": prm.finish_costs.get(inp.finish, 0.0),
        "etching": inp.etching_cost,
        "masking": inp.masking_cost,
        "silkscreen": inp.silkscreen_cost,
    }
    treatment_cost = _component_total(treatment_components)

    # Process cost
    mr = prm.machine_rates
    process_components = {
        "direct_pth": mr.get("direct_pth_per_hole", 0.0) * max(0, inp.direct_pth_holes) * boards_per_panel,
        "cnc_pth": mr.get("cnc_pth_per_hole", 0.0) * max(0, inp.cnc_pth_holes) * boards_per_panel,
        "cutting": _non_negative(inp.cutting_cost),
        "routing": _non_negative(inp.routing_cost),
        "e_test": _non_negative(inp.e_test_cost),
        "v_cut": _non_negative(inp.v_cut_cost),
        "fqc": _non_negative(inp.fqc_cost),
        "package": _non_negative(inp.package_cost),
    }
    process_cost = _component_total(process_components)

    # Sewage cost
    sewage_components = {
        "water": inp.sewage_water,
        "electricity": inp.sewage_electricity,
    }
    sewage_cost = _component_total(sewage_components)

    base = material_cost + treatment_cost + process_cost + sewage_cost

    # Other cost
    oh = base * _non_negative(prm.overheads_pct) / 100.0
    yield_pct = _percent(prm.yield_pct)
    yld = base * (100.0 - yield_pct) / 100.0
    zone_factor = prm.ship_zone_factor.get(inp.ship_zone, 1.0)
    logistics_factor = max(zone_factor - 1.0, 0.0)
    logistics_cost = (base + oh + yld) * logistics_factor
    other_cost = oh + yld + logistics_cost

    # Total COGs
    cogs = base + oh + yld + logistics_cost

    cogs_unit = cogs / boards_per_panel if boards_per_panel else 0.0
    price_unit = cogs_unit * (1 + prm.margin_pct / 100.0)

    breakdown = {
        "material": {
            "total": round(material_cost, 2),
            "components": _rounded(material_components, 2),
        },
        "treatment": {
            "total": round(treatment_cost, 2),
            "components": _rounded(treatment_components, 2),
        },
        "process": {
            "total": round(process_cost, 1),
            "components": _rounded(process_components, 1),
        },
        "sewage": {
            "total": round(sewage_cost, 2),
            "components": _rounded(sewage_components, 2),
        },
        "others": {
            "total": round(other_cost, 2),
            "ship_zone": inp.ship_zone,
            "factor": round(zone_factor, 3),
            "logistic": round(logistics_cost, 2),
            "overhead": round(oh, 2),
            "yield_pct": round(yield_pct, 2),
        },
        "boards_per_panel": boards_per_panel,
    }
    return {
        "cogs": round(cogs, 2),
        "cogs_unit": round(cogs_unit, 4),
        "price_unit": round(price_unit, 4),
        "breakdown": breakdown,
    }
