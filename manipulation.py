from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

@dataclass
class Inputs:
    layers: int
    panel_boards: int
    stack_qty: int
    pcb_thickness: str
    cnc_hole_dimension: str
    cnc_pth_holes: int
    material: str
    substrate_thickness: str
    cu_thickness: str
    finish: str
    plating: str
    etching_cost: float
    masking: str
    silkscreen_cost: float
    routing_length: float
    stamping_cost: float
    post_process_cost: float
    sewage_water: float
    sewage_electricity: float

@dataclass
class Params:
    material_costs: dict[str, dict[str, dict[str, float]]]
    finish_costs: dict
    masking_costs: dict
    plating_costs: dict
    labor_cost: float
    loss_pct: float
    margin_pct: float
    cnc_pth_per_hole: float
    routing_per_inch: float

def _non_negative(value: float) -> float:
    return max(value, 0.0)

def _percent(value: float) -> float:
    return max(0.0, min(100.0, value))

def _component_total(components: Mapping[str, float]) -> float:
    return sum(components.values())

def _rounded(components: Mapping[str, float], digits: int) -> dict:
    return {name: round(amount, digits) for name, amount in components.items()}


def _component_section(total: float, components: Mapping[str, float], digits: int) -> dict:
    """Prepare a rounded breakdown entry for a cost category."""
    return {"total": round(total, digits), "components": _rounded(components, digits)}

def price_quote(inp: Inputs, prm: Params) -> dict:

    boards_per_panel = max(1, int(inp.panel_boards) if inp.panel_boards else 1)
    stack_qty = max(1, int(inp.stack_qty) if inp.stack_qty else 1)

    # Material cost
    laminate_cost = 15.0
    material_map = prm.material_costs.get(inp.material)
    if isinstance(material_map, dict):
        substrate_map = material_map.get(inp.substrate_thickness)
        if isinstance(substrate_map, dict):
            laminate_cost = substrate_map.get(inp.cu_thickness, laminate_cost)
    material_components = {
        "laminate": laminate_cost,
    }
    material_cost = _component_total(material_components)

    # Treatment cost
    treatment_components = {
        "finish": prm.finish_costs.get(inp.finish, 0.0),
        "etching": inp.etching_cost,
        "masking": prm.masking_costs.get(inp.masking, 0.0),
        "silkscreen": inp.silkscreen_cost,
    }
    treatment_cost = _component_total(treatment_components)

    # CNC drilling cost
    cnc_rate = _non_negative(prm.cnc_pth_per_hole)
    cnc_components = {
        "cnc_pth": cnc_rate * max(0, inp.cnc_pth_holes) ,
    }
    cnc_stack_cost = _component_total(cnc_components)
    cnd_cost_panel = cnc_stack_cost / stack_qty if stack_qty else cnc_stack_cost
    cnc_cost = cnd_cost_panel

    # Process cost
    routing_length = _non_negative(inp.routing_length)
    routing_rate = _non_negative(prm.routing_per_inch)
    process_components = {
        "plating": prm.plating_costs.get(inp.plating, 0.0),
        "routing": routing_length * routing_rate,
        "stamping": _non_negative(inp.stamping_cost),
        "post_process": _non_negative(inp.post_process_cost),
    }
    process_cost = _component_total(process_components)

    # Overhead cost (formerly Sewage) now includes labor
    labor_cost = _non_negative(prm.labor_cost)
    overhead_components = {
        "water": _non_negative(inp.sewage_water),
        "electricity": _non_negative(inp.sewage_electricity),
        "labor": labor_cost,
    }
    overhead_cost = _component_total(overhead_components)

    base = (
        material_cost
        + treatment_cost
        + cnc_cost
        + process_cost
        + overhead_cost
    )

    loss_pct = _percent(prm.loss_pct)
    cogs = base * (1 + loss_pct / 100.0)
    loss_cost = cogs - base

    cogs_unit = cogs / boards_per_panel if boards_per_panel else 0.0
    margin_pct = _non_negative(prm.margin_pct)
    price_unit = cogs_unit * (1 + margin_pct / 100.0)
    margin_cost = cogs * margin_pct / 100.0

    overhead_section = _component_section(overhead_cost, overhead_components, 2)
    loss_rounded = round(loss_cost, 2)
    rounded_others = {
        "total": loss_rounded,
        "overhead": overhead_section["total"],
        "loss": loss_rounded,
        "margin": round(margin_cost, 2),
    }

    breakdown = {
        "material": _component_section(material_cost, material_components, 2),
        "treatment": _component_section(treatment_cost, treatment_components, 2),
        "cnc": {
            "total": round(cnc_cost, 1),
            "cnd_cost_panel": round(cnd_cost_panel, 1),
            "stack_qty": stack_qty,
            "components": _rounded(cnc_components, 1),
        },
        "process": _component_section(process_cost, process_components, 1),
        "overhead": overhead_section,
        "others": rounded_others,
        "boards_per_panel": boards_per_panel,
    }
    return {
        "cogs": round(cogs, 2),
        "cogs_unit": round(cogs_unit, 4),
        "price_unit": round(price_unit, 4),
        "breakdown": breakdown,
    }


# ============================================================================
# PANELIZER MODULE: Panel sizing and layout optimization
# ============================================================================

PANELIZER_CONFIG_KEYS: tuple[str, ...] = (
    "customer_board_width_max",
    "customer_board_length_max",
    "customer_board_width_min",
    "customer_board_length_min",
    "single_pcb_width_max",
    "single_pcb_length_max",
    "panel_edge_margin_w",
    "panel_edge_margin_l",
    "board_edge_margin_w",
    "board_edge_margin_l",
    "inter_board_gap_w",
    "inter_board_gap_l",
    "inter_single_gap_w",
    "inter_single_gap_l",
    "allow_rotate_board",
    "allow_rotate_single_pcb",
    "limit",
    "include_set_A",
    "include_set_B",
    "include_set_C",
    "include_set_D",
    "include_set_E",
)


class PanelizerContext:
    """Context for panelizer configuration and state."""

    def __init__(
        self,
        defaults: Dict[str, Any],
        panel_options: Dict[str, Tuple[float, float]],
        jumbo_multiplier: Dict[str, int],
    ):
        self.defaults = defaults
        self.panel_options = panel_options
        self.jumbo_multiplier = jumbo_multiplier


def build_panelizer_config(
    args: Any, defaults: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Build panelizer configuration from form arguments and defaults.

    Args:
        args: Form arguments (dict-like with get method)
        defaults: Default values from presets

    Returns:
        Complete panelizer configuration dictionary
    """
    missing = [key for key in PANELIZER_CONFIG_KEYS if key not in defaults]
    if missing:
        missing_csv = ", ".join(sorted(missing))
        raise RuntimeError(f"Panelizer defaults missing from presets: {missing_csv}")

    cfg = {key: defaults[key] for key in PANELIZER_CONFIG_KEYS}

    cfg["customer_board_width_max"] = _panelizer_float(
        args, "CBW", cfg.get("customer_board_width_max", 0.0)
    )
    cfg["customer_board_length_max"] = _panelizer_float(
        args, "CBL", cfg.get("customer_board_length_max", 0.0)
    )
    cfg["customer_board_width_min"] = _panelizer_float(
        args, "CBWM", cfg.get("customer_board_width_min", 0.0)
    )
    cfg["customer_board_length_min"] = _panelizer_float(
        args, "CBLM", cfg.get("customer_board_length_min", 0.0)
    )
    cfg["single_pcb_width_max"] = _panelizer_float(
        args, "SPW", cfg.get("single_pcb_width_max", 0.0)
    )
    cfg["single_pcb_length_max"] = _panelizer_float(
        args, "SPL", cfg.get("single_pcb_length_max", 0.0)
    )
    cfg["panel_edge_margin_w"] = _panelizer_float(
        args, "PEW", cfg.get("panel_edge_margin_w", 0.0)
    )
    cfg["panel_edge_margin_l"] = _panelizer_float(
        args, "PEL", cfg.get("panel_edge_margin_l", 0.0)
    )
    cfg["board_edge_margin_w"] = _panelizer_float(
        args, "BMW", cfg.get("board_edge_margin_w", 0.0)
    )
    cfg["board_edge_margin_l"] = _panelizer_float(
        args, "BML", cfg.get("board_edge_margin_l", 0.0)
    )
    cfg["inter_board_gap_w"] = _panelizer_float(
        args, "CW", cfg.get("inter_board_gap_w", 0.0)
    )
    cfg["inter_board_gap_l"] = _panelizer_float(
        args, "CL", cfg.get("inter_board_gap_l", 0.0)
    )
    cfg["inter_single_gap_w"] = _panelizer_float(
        args, "SW", cfg.get("inter_single_gap_w", 0.0)
    )
    cfg["inter_single_gap_l"] = _panelizer_float(
        args, "SL", cfg.get("inter_single_gap_l", 0.0)
    )
    cfg["allow_rotate_board"] = _panelizer_checkbox(
        args, "ARB", cfg.get("allow_rotate_board", False)
    )
    cfg["allow_rotate_single_pcb"] = _panelizer_checkbox(
        args, "ARS", cfg.get("allow_rotate_single_pcb", False)
    )
    cfg["limit"] = _panelizer_int(args, "LIMIT", int(cfg.get("limit", 10)))
    for letter in "ABCDE":
        cfg[f"include_set_{letter}"] = _panelizer_checkbox(
            args, f"SET_{letter}", cfg.get(f"include_set_{letter}", False)
        )
    return cfg


def compute_panelizer_rows(
    cfg: Dict[str, Any],
    panel_options: Dict[str, Tuple[float, float]],
    jumbo_multiplier: Dict[str, int],
) -> List[Dict[str, Any]]:
    """
    Compute all feasible panelizer layout rows.

    Args:
        cfg: Panelizer configuration
        panel_options: Available panel sizes by style
        jumbo_multiplier: Multiplier for PCBs per jumbo by style

    Returns:
        List of layout dictionaries, sorted by optimality
    """
    enabled_sets = {
        letter for letter in "ABCDE" if cfg.get(f"include_set_{letter}", False)
    }
    if not enabled_sets:
        return []

    rows: List[Dict[str, Any]] = []
    for style, (pw, pl) in panel_options.items():
        if style[:1].upper() not in enabled_sets:
            continue
        rows.extend(
            _panelizer_enumerate_layouts(cfg, pw, pl, style, jumbo_multiplier)
        )

    rows.sort(
        key=lambda r: (
            -r["utilization"],
            -r["pcbs_per_jumbo"],
            r["objective_key"],
        )
    )
    return _panelizer_deduplicate_rows(rows)


def summarize_panelizer_results(
    rows: List[Dict[str, Any]], cfg: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Create summary of panelizer results for display.

    Args:
        rows: List of layout rows
        cfg: Panelizer configuration (for limit)

    Returns:
        Summary dictionary with display information
    """
    limit = int(cfg.get("limit", 10))
    total = len(rows)
    shown = min(total, limit)
    display_rows = rows[:shown]

    if rows:
        message = (
            f"Found {total} feasible layouts. Showing top {shown} by Utilization."
        )
    else:
        message = "No feasible layouts under current constraints."

    max_util = max((r["utilization"] for r in rows), default=None)
    star_message = (
        "Highest utilization shown with ★" if max_util is not None else ""
    )
    table_attrs = "" if display_rows else 'style="display:none"'

    return {
        "rows": display_rows,
        "message": message,
        "limit": limit,
        "total": total,
        "shown": shown,
        "highest_ultilization_per_jumbo": max_util,
        "star_message": star_message,
        "table_attrs": table_attrs,
    }


# ============================================================================
# PANELIZER: Internal Helper Functions
# ============================================================================


def _panelizer_parse_bool(value: Any) -> bool:
    """Parse boolean from string or value."""
    if isinstance(value, str):
        return value.lower() in ("1", "true", "on", "yes")
    return bool(value)


def _panelizer_checkbox(args: Any, key: str, default: bool) -> bool:
    """Extract checkbox value from form arguments."""
    if key in args:
        raw = args.get(key, "on")
        normalized = "on" if raw in (None, "") else raw
        return _panelizer_parse_bool(normalized)
    if not args:
        return default
    return False


def _panelizer_float(args: Any, key: str, default: float) -> float:
    """Extract and convert float value from form arguments."""
    raw = args.get(key)
    if raw in (None, ""):
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _panelizer_int(args: Any, key: str, default: int) -> int:
    """Extract and convert int value from form arguments."""
    raw = args.get(key)
    if raw in (None, ""):
        return int(default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def _panelizer_almost_le(a: float, b: float, eps: float = 1e-9) -> bool:
    """Approximately less than or equal (with tolerance)."""
    return a <= b + eps


def _panelizer_almost_ge(a: float, b: float, eps: float = 1e-9) -> bool:
    """Approximately greater than or equal (with tolerance)."""
    return a + eps >= b


def _panelizer_rects_overlap_1d(
    a0: float, a1: float, b0: float, b1: float, eps: float = 1e-9
) -> bool:
    """Check if two 1D ranges overlap (with tolerance)."""
    return (a0 < b1 - eps) and (b0 < a1 - eps)


def _panelizer_pairwise_no_overlap(
    rects: List[Tuple[float, float, float, float]], eps: float = 1e-9
) -> bool:
    """Check if no pairs of rectangles overlap."""
    n = len(rects)
    for i in range(n):
        xi0, yi0, xi1, yi1 = rects[i]
        for j in range(i + 1, n):
            xj0, yj0, xj1, yj1 = rects[j]
            if _panelizer_rects_overlap_1d(
                xi0, xi1, xj0, xj1, eps
            ) and _panelizer_rects_overlap_1d(yi0, yi1, yj0, yj1, eps):
                return False
    return True


def _panelizer_upper_bound_grid(max_len: float, item: float, gap: float) -> int:
    """Calculate upper bound for grid dimension."""
    if item <= 0:
        return 0
    return max(0, int(math.floor((max_len + gap) / (item + gap))))


def _panelizer_utilization(
    total_single_pcbs: int, spw: float, spl: float, wpw: float, wpl: float
) -> float:
    """Calculate panel utilization ratio."""
    return (
        (total_single_pcbs * spw * spl) / (wpw * wpl) if wpw > 0 and wpl > 0 else 0.0
    )


def _panelizer_enumerate_layouts(
    cfg: Dict[str, float],
    panel_w: float,
    panel_l: float,
    panel_style: str,
    jumbo_multiplier: Dict[str, int],
) -> List[Dict[str, Any]]:
    """Enumerate all feasible layout configurations for a panel style."""
    WPW = float(panel_w)
    WPL = float(panel_l)
    CBW = float(cfg["customer_board_width_max"])
    CBL = float(cfg["customer_board_length_max"])
    CBW_min = float(cfg.get("customer_board_width_min", 0.0))
    CBL_min = float(cfg.get("customer_board_length_min", 0.0))
    SPW = float(cfg["single_pcb_width_max"])
    SPL = float(cfg["single_pcb_length_max"])
    # Skip heavy enumeration until both dimensions exceed the safe threshold.
    if SPW <= 15.0 or SPL <= 15.0:
        return []
    PEW = float(cfg["panel_edge_margin_w"])
    PEL = float(cfg["panel_edge_margin_l"])
    BEW = float(cfg.get("board_edge_margin_w", 0.0))
    BEL = float(cfg.get("board_edge_margin_l", 0.0))
    CW = float(cfg["inter_board_gap_w"])
    CL = float(cfg["inter_board_gap_l"])
    SW = float(cfg["inter_single_gap_w"])
    SL = float(cfg["inter_single_gap_l"])
    allow_rotate_board = bool(cfg.get("allow_rotate_board", False))
    allow_rotate_single = bool(cfg.get("allow_rotate_single_pcb", False))
    CWi, CLi = CW, CL
    SWi, SLi = SW, SL

    panel_area = WPW * WPL

    layouts: List[Dict[str, Any]] = []
    board_rot_options = [False, True] if allow_rotate_board else [False]
    single_rot_options = [False, True] if allow_rotate_single else [False]

    # Jumbo multiplier is fixed for this panel_style; track best for branch-and-bound.
    jmul = jumbo_multiplier.get(panel_style, 1)
    best_pcbs_per_jumbo = 0

    for board_rot in board_rot_options:
        if board_rot:
            CBW_eff, CBL_eff = CBL, CBW
            CBW_min_eff, CBL_min_eff = CBL_min, CBW_min
            margin_w_eff, margin_l_eff = BEL, BEW
        else:
            CBW_eff, CBL_eff = CBW, CBL
            CBW_min_eff, CBL_min_eff = CBW_min, CBL_min
            margin_w_eff, margin_l_eff = BEW, BEL

        max_inner_w = CBW_eff - 2.0 * margin_w_eff
        max_inner_l = CBL_eff - 2.0 * margin_l_eff
        if max_inner_w <= 0 or max_inner_l <= 0:
            continue

        for single_rot in single_rot_options:
            spw_eff, spl_eff = (SPL, SPW) if single_rot else (SPW, SPL)

            ub_nw = _panelizer_upper_bound_grid(max_inner_w, spw_eff, SWi)
            ub_nl = _panelizer_upper_bound_grid(max_inner_l, spl_eff, SLi)
            if ub_nw == 0 or ub_nl == 0:
                continue

            for nw in range(1, ub_nw + 1):
                single_grid_w = nw * spw_eff + (nw - 1) * SWi
                if not _panelizer_almost_le(single_grid_w, max_inner_w):
                    continue
                for nl in range(1, ub_nl + 1):
                    single_grid_l = nl * spl_eff + (nl - 1) * SLi
                    if not _panelizer_almost_le(single_grid_l, max_inner_l):
                        continue

                    board_w = single_grid_w + 2.0 * margin_w_eff
                    board_l = single_grid_l + 2.0 * margin_l_eff
                    if not _panelizer_almost_ge(
                        board_w, CBW_min_eff
                    ) or not _panelizer_almost_ge(board_l, CBL_min_eff):
                        continue
                    avail_w = WPW - 2.0 * PEW
                    avail_l = WPL - 2.0 * PEL
                    if avail_w <= 0 or avail_l <= 0:
                        continue

                    ub_nbw = _panelizer_upper_bound_grid(avail_w, board_w, CWi)
                    ub_nbl = _panelizer_upper_bound_grid(avail_l, board_l, CLi)
                    if ub_nbw == 0 or ub_nbl == 0:
                        continue

                    # Branch & bound: for這組 (nw, nl)，在理論最多放滿 ub_nbw × ub_nbl 塊大板的情況下，
                    # 仍然無法達到目前 best_pcbs_per_jumbo，就不需要再枚舉 nbw, nbl。
                    max_pcbs_this = ub_nbw * ub_nbl * nw * nl * jmul
                    if max_pcbs_this < best_pcbs_per_jumbo:
                        continue

                    for nbw in range(1, ub_nbw + 1):
                        panel_used_w = nbw * board_w + (nbw - 1) * CWi + 2.0 * PEW
                        if not _panelizer_almost_le(panel_used_w, WPW):
                            continue
                        for nbl in range(1, ub_nbl + 1):
                            panel_used_l = (
                                nbl * board_l + (nbl - 1) * CLi + 2.0 * PEL
                            )
                            if not _panelizer_almost_le(panel_used_l, WPL):
                                continue

                            total_single_pcbs = nbw * nbl * nw * nl
                            util = _panelizer_utilization(
                                total_single_pcbs, SPW, SPL, WPW, WPL
                            )
                            pcbs_per_jumbo = total_single_pcbs * jmul
                            unused_area = panel_area - panel_used_w * panel_used_l
                            rotations_count = (
                                (1 if board_rot else 0)
                                + (1 if single_rot else 0)
                            )
                            left_margin = PEW
                            bottom_margin = PEL
                            right_margin = WPW - panel_used_w
                            top_margin = WPL - panel_used_l
                            mu_score = abs(left_margin - right_margin) + abs(
                                bottom_margin - top_margin
                            )

                            board_origins = []
                            x0, y0 = PEW, PEL
                            for j in range(nbl):
                                y = y0 + j * (board_l + CLi)
                                for i in range(nbw):
                                    x = x0 + i * (board_w + CWi)
                                    board_origins.append(
                                        {"x": x, "y": y, "rotated": board_rot}
                                    )

                            single_origins = []
                            sx0, sy0 = margin_w_eff, margin_l_eff
                            for jl in range(nl):
                                sy = sy0 + jl * (spl_eff + SLi)
                                for iw in range(nw):
                                    sx = sx0 + iw * (spw_eff + SWi)
                                    single_origins.append(
                                        {"x": sx, "y": sy, "rotated": single_rot}
                                    )

                            all_ok = True
                            failure: Optional[str] = None

                            if all_ok:
                                # 這裡直接重用 spw_eff, spl_eff，避免重複計算。
                                spw_e, spl_e = spw_eff, spl_eff
                                single_rects = []
                                for so in single_origins:
                                    sx, sy = so["x"], so["y"]
                                    single_rects.append(
                                        (sx, sy, sx + spw_e, sy + spl_e)
                                    )
                                    if (
                                        sx < 0
                                        or sy < 0
                                        or (sx + spw_e) > board_w
                                        or (sy + spl_e) > board_l
                                    ):
                                        all_ok, failure = (
                                            False,
                                            "Single out of board bounds",
                                        )
                                        break
                                if all_ok and not _panelizer_pairwise_no_overlap(
                                    single_rects
                                ):
                                    all_ok, failure = False, "Singles overlap"

                            # 只有在「幾何完全可行」時，才更新 best_pcbs_per_jumbo，
                            # 確保剪枝只根據真正可行解的上界，不會漏掉最優可行解。
                            if all_ok and pcbs_per_jumbo > best_pcbs_per_jumbo:
                                best_pcbs_per_jumbo = pcbs_per_jumbo

                            layouts.append(
                                {
                                    "total_single_pcbs": total_single_pcbs,
                                    "utilization": util,
                                    "unused_area": unused_area,
                                    "nbw": nbw,
                                    "nbl": nbl,
                                    "nw": nw,
                                    "nl": nl,
                                    "board_rot": board_rot,
                                    "single_rot": single_rot,
                                    "board_w": board_w,
                                    "board_l": board_l,
                                    "panel_used_w": panel_used_w,
                                    "panel_used_l": panel_used_l,
                                    "panel_style": panel_style,
                                    "panel_width": WPW,
                                    "panel_length": WPL,
                                    "pcbs_per_jumbo": pcbs_per_jumbo,
                                    "margins": {
                                        "left": left_margin,
                                        "right": right_margin,
                                        "bottom": bottom_margin,
                                        "top": top_margin,
                                    },
                                    "margin_uniformity": mu_score,
                                    "rotations_count": rotations_count,
                                    "placements": {
                                        "boards": board_origins,
                                        "singles_per_board": single_origins,
                                    },
                                    "all_constraints_satisfied": all_ok,
                                    "first_failure": failure,
                                    "objective_key": (
                                        -total_single_pcbs,
                                        -util,
                                        unused_area,
                                        mu_score,
                                        rotations_count,
                                    ),
                                }
                            )
    return layouts


def _panelizer_rotation_priority(row: Dict[str, Any]) -> int:
    """Assign priority based on rotation state (lower is better)."""
    board_rot = row.get("board_rot", False)
    single_rot = row.get("single_rot", False)
    if not board_rot and not single_rot:
        return 0
    if board_rot and not single_rot:
        return 1
    if not board_rot and single_rot:
        return 2
    return 3


def _panelizer_deduplicate_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate layouts, keeping best rotation variant."""
    seen_order: List[Tuple[str, int, int, int, int, int]] = []
    best: Dict[Tuple[str, int, int, int, int, int], Dict[str, Any]] = {}
    for row in rows:
        key = (
            row.get("panel_style"),
            row["total_single_pcbs"],
            row["nbw"],
            row["nbl"],
            row["nw"],
            row["nl"],
        )
        if key not in best:
            best[key] = row
            seen_order.append(key)
            continue
        current = best[key]
        if _panelizer_rotation_priority(row) < _panelizer_rotation_priority(current):
            best[key] = row
    return [best[key] for key in seen_order]
