from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, fields
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, get_type_hints

from flask import Flask, render_template, request, send_file

from manipulation import Inputs, Params, price_quote

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Configuration & preset loading
# ---------------------------------------------------------------------------

ICON_FILENAME = "lt.png"
ICON_PATH = os.path.join(os.path.dirname(__file__), ICON_FILENAME)
BASE_PRESETS_PATH = os.path.join(os.path.dirname(__file__), "presets_qp.json")
LOCAL_PRESETS_PATH = os.environ.get(
    "PRESETS_OVERRIDE_PATH",
    os.path.join(os.path.dirname(__file__), "presets_qp.local.json"),
)


def _load_json(path: str, *, required: bool = False) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        if required:
            raise
        return {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {path}: {exc}") from exc


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = base.copy()
    for key, value in override.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(base_value, value)
        else:
            merged[key] = value
    return merged


PRESETS_BASE = _load_json(BASE_PRESETS_PATH, required=True)
PRESETS_OVERRIDE = _load_json(LOCAL_PRESETS_PATH)
PRESETS = _deep_merge(PRESETS_BASE, PRESETS_OVERRIDE)
DEFAULTS = PRESETS["defaults"]
INPUT_TYPE_HINTS = get_type_hints(Inputs)
PARAM_TYPE_HINTS = get_type_hints(Params)
INPUT_FIELD_NAMES = tuple(f.name for f in fields(Inputs))

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
    "kerf_allowance",
    "limit",
    "include_set_A",
    "include_set_B",
    "include_set_C",
    "include_set_D",
    "include_set_E",
)


# ---------------------------------------------------------------------------
# Data structures & default-derived options
# ---------------------------------------------------------------------------

class PricedField(NamedTuple):
    name: str
    price_field: str
    map_key: str
    error: str


PRICED_FIELDS: tuple[PricedField, ...] = (
    PricedField("material", "material_price", "material_costs", "Material price must be a number"),
    PricedField("finish", "finish_price", "finish_costs", "Finish cost must be a number"),
    PricedField("masking", "masking_price", "masking_costs", "Masking cost must be a number"),
    PricedField("plating", "plating_price", "plating_costs", "Plating cost must be a number"),
)


def _defaults_map(key: str) -> dict[str, Any]:
    value = DEFAULTS.get(key, {})
    return value.copy() if isinstance(value, dict) else {}


def _options_from_defaults(map_key: str) -> tuple[str, ...]:
    mapping = DEFAULTS.get(map_key, {})
    return tuple(mapping.keys()) if isinstance(mapping, dict) else tuple()


PRICED_DEFAULT_MAPS = {field.name: _defaults_map(field.map_key) for field in PRICED_FIELDS}
SELECT_OPTIONS = {field.name: tuple(PRICED_DEFAULT_MAPS[field.name].keys()) for field in PRICED_FIELDS}
PCB_THICKNESS_OPTIONS = _options_from_defaults("pcb_thickness_options")
CNC_HOLE_DIMENSION_OPTIONS = _options_from_defaults("cnc_hole_dimension_options")


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------


def _stack_qty_lookup(thickness: str | None, hole_dimension: str | None) -> int | None:
    mapping = DEFAULTS.get("stack_qty_map")
    if not isinstance(mapping, dict):
        return None
    thickness_map = mapping.get(thickness)
    if not isinstance(thickness_map, dict):
        return None
    value = thickness_map.get(hole_dimension)
    if value is None:
        return None
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return None


def _persist_defaults(
    inputs: Inputs,
    params: Params,
    panelizer_cfg: Optional[Dict[str, Any]] = None,
) -> None:
    updated_defaults = DEFAULTS.copy()
    updated_defaults.update(asdict(inputs))
    updated_defaults.update(asdict(params))
    if panelizer_cfg:
        for key in PANELIZER_CONFIG_KEYS:
            if key in panelizer_cfg:
                updated_defaults[key] = panelizer_cfg[key]

    try:
        PRESETS_OVERRIDE["defaults"] = updated_defaults
        with open(LOCAL_PRESETS_PATH, "w", encoding="utf-8") as f:
            json.dump(PRESETS_OVERRIDE, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as exc:
        raise RuntimeError(f"Failed to update presets: {exc}") from exc

    DEFAULTS.clear()
    DEFAULTS.update(updated_defaults)
    PRESETS["defaults"] = DEFAULTS

    global PCB_THICKNESS_OPTIONS, CNC_HOLE_DIMENSION_OPTIONS
    PCB_THICKNESS_OPTIONS = _options_from_defaults("pcb_thickness_options")
    CNC_HOLE_DIMENSION_OPTIONS = _options_from_defaults("cnc_hole_dimension_options")

    for field in PRICED_FIELDS:
        defaults_map = _defaults_map(field.map_key)
        PRICED_DEFAULT_MAPS[field.name] = defaults_map
        SELECT_OPTIONS[field.name] = tuple(defaults_map.keys())

    # NOTE: Mutates DEFAULTS/PRESETS in place so later requests see the new defaults.


# ---------------------------------------------------------------------------
# Panelizer configuration & layout search
# ---------------------------------------------------------------------------


def _panelizer_section(key: str) -> Dict[str, Any]:
    value = DEFAULTS.get(key, {})
    return value.copy() if isinstance(value, dict) else {}


def _load_panelizer_panel_options() -> Dict[str, Tuple[float, float]]:
    section = _panelizer_section("panelizer_panel_options")
    if not section:
        raise RuntimeError("panelizer_panel_options is missing from defaults.")
    options: Dict[str, Tuple[float, float]] = {}
    for style, dims in section.items():
        if not isinstance(dims, (list, tuple)) or len(dims) != 2:
            raise ValueError(f"Invalid panel dimensions for {style!r}")
        options[style] = (float(dims[0]), float(dims[1]))
    return options


def _load_panelizer_jumbo_multiplier() -> Dict[str, int]:
    section = _panelizer_section("panelizer_jumbo_multiplier")
    if not section:
        raise RuntimeError("panelizer_jumbo_multiplier is missing from defaults.")
    multipliers: Dict[str, int] = {}
    for style, value in section.items():
        multipliers[style] = int(value)
    return multipliers


PANELIZER_PANEL_OPTIONS = _load_panelizer_panel_options()
PANELIZER_JUMBO_MULTIPLIER = _load_panelizer_jumbo_multiplier()


def _panelizer_default_config() -> Dict[str, Any]:
    missing = [key for key in PANELIZER_CONFIG_KEYS if key not in DEFAULTS]
    if missing:
        missing_csv = ", ".join(sorted(missing))
        raise RuntimeError(f"Panelizer defaults missing from presets: {missing_csv}")
    return {key: DEFAULTS[key] for key in PANELIZER_CONFIG_KEYS}


def _panelizer_parse_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower() in ("1", "true", "on", "yes")
    return bool(value)


def _panelizer_checkbox(args, key: str, default: bool) -> bool:
    if key in args:
        raw = args.get(key, "on")
        normalized = "on" if raw in (None, "") else raw
        return _panelizer_parse_bool(normalized)
    if not args:
        return default
    return False


def _panelizer_float(args, key: str, default: float) -> float:
    raw = args.get(key)
    if raw in (None, ""):
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _panelizer_int(args, key: str, default: int) -> int:
    raw = args.get(key)
    if raw in (None, ""):
        return int(default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def _panelizer_config(args) -> Dict[str, Any]:
    cfg = _panelizer_default_config()
    cfg["customer_board_width_max"] = _panelizer_float(args, "CBW", cfg.get("customer_board_width_max", 0.0))
    cfg["customer_board_length_max"] = _panelizer_float(args, "CBL", cfg.get("customer_board_length_max", 0.0))
    cfg["customer_board_width_min"] = _panelizer_float(args, "CBWM", cfg.get("customer_board_width_min", 0.0))
    cfg["customer_board_length_min"] = _panelizer_float(args, "CBLM", cfg.get("customer_board_length_min", 0.0))
    cfg["single_pcb_width_max"] = _panelizer_float(args, "SPW", cfg.get("single_pcb_width_max", 0.0))
    cfg["single_pcb_length_max"] = _panelizer_float(args, "SPL", cfg.get("single_pcb_length_max", 0.0))
    cfg["panel_edge_margin_w"] = _panelizer_float(args, "EW_w", cfg.get("panel_edge_margin_w", 0.0))
    cfg["panel_edge_margin_l"] = _panelizer_float(args, "EW_l", cfg.get("panel_edge_margin_l", 0.0))
    cfg["board_edge_margin_w"] = _panelizer_float(args, "BMW", cfg.get("board_edge_margin_w", 0.0))
    cfg["board_edge_margin_l"] = _panelizer_float(args, "BML", cfg.get("board_edge_margin_l", 0.0))
    cfg["inter_board_gap_w"] = _panelizer_float(args, "CW", cfg.get("inter_board_gap_w", 0.0))
    cfg["inter_board_gap_l"] = _panelizer_float(args, "CL", cfg.get("inter_board_gap_l", 0.0))
    cfg["inter_single_gap_w"] = _panelizer_float(args, "SW", cfg.get("inter_single_gap_w", 0.0))
    cfg["inter_single_gap_l"] = _panelizer_float(args, "SL", cfg.get("inter_single_gap_l", 0.0))
    cfg["allow_rotate_board"] = _panelizer_checkbox(args, "ARB", cfg.get("allow_rotate_board", False))
    cfg["allow_rotate_single_pcb"] = _panelizer_checkbox(args, "ARS", cfg.get("allow_rotate_single_pcb", False))
    cfg["kerf_allowance"] = _panelizer_float(args, "KERF", cfg.get("kerf_allowance", 0.0))
    cfg["limit"] = _panelizer_int(args, "LIMIT", int(cfg.get("limit", 10)))
    for letter in "ABCDE":
        cfg[f"include_set_{letter}"] = _panelizer_checkbox(args, f"SET_{letter}", cfg.get(f"include_set_{letter}", False))
    return cfg


def _panelizer_almost_le(a: float, b: float, eps: float = 1e-9) -> bool:
    return a <= b + eps


def _panelizer_almost_ge(a: float, b: float, eps: float = 1e-9) -> bool:
    return a + eps >= b


def _panelizer_rects_overlap_1d(a0: float, a1: float, b0: float, b1: float, eps: float = 1e-9) -> bool:
    return (a0 < b1 - eps) and (b0 < a1 - eps)


def _panelizer_pairwise_no_overlap(rects: List[Tuple[float, float, float, float]], eps: float = 1e-9) -> bool:
    n = len(rects)
    for i in range(n):
        xi0, yi0, xi1, yi1 = rects[i]
        for j in range(i + 1, n):
            xj0, yj0, xj1, yj1 = rects[j]
            if _panelizer_rects_overlap_1d(xi0, xi1, xj0, xj1, eps) and _panelizer_rects_overlap_1d(yi0, yi1, yj0, yj1, eps):
                return False
    return True


def _panelizer_upper_bound_grid(max_len: float, item: float, gap: float) -> int:
    if item <= 0:
        return 0
    return max(0, int(math.floor((max_len + gap) / (item + gap))))


def _panelizer_utilization(total_single_pcbs: int, spw: float, spl: float, wpw: float, wpl: float) -> float:
    return (total_single_pcbs * spw * spl) / (wpw * wpl) if wpw > 0 and wpl > 0 else 0.0


def _panelizer_enumerate_layouts(cfg: Dict[str, float], panel_w: float, panel_l: float, panel_style: str) -> List[Dict[str, Any]]:
    WPW = float(panel_w)
    WPL = float(panel_l)
    CBW = float(cfg["customer_board_width_max"])
    CBL = float(cfg["customer_board_length_max"])
    CBW_min = float(cfg.get("customer_board_width_min", 0.0))
    CBL_min = float(cfg.get("customer_board_length_min", 0.0))
    SPW = float(cfg["single_pcb_width_max"])
    SPL = float(cfg["single_pcb_length_max"])
    EW_w = float(cfg["panel_edge_margin_w"])
    EW_l = float(cfg["panel_edge_margin_l"])
    BEW = float(cfg.get("board_edge_margin_w", 0.0))
    BEL = float(cfg.get("board_edge_margin_l", 0.0))
    CW = float(cfg["inter_board_gap_w"])
    CL = float(cfg["inter_board_gap_l"])
    SW = float(cfg["inter_single_gap_w"])
    SL = float(cfg["inter_single_gap_l"])
    allow_rotate_board = bool(cfg.get("allow_rotate_board", False))
    allow_rotate_single = bool(cfg.get("allow_rotate_single_pcb", False))
    kerf = float(cfg.get("kerf_allowance", 0.0))

    CWi, CLi = CW + kerf, CL + kerf
    SWi, SLi = SW + kerf, SL + kerf

    panel_area = WPW * WPL

    layouts: List[Dict[str, Any]] = []
    board_rot_options = [False, True] if allow_rotate_board else [False]
    single_rot_options = [False, True] if allow_rotate_single else [False]

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
                    if not _panelizer_almost_ge(board_w, CBW_min_eff) or not _panelizer_almost_ge(board_l, CBL_min_eff):
                        continue
                    avail_w = WPW - 2.0 * EW_w
                    avail_l = WPL - 2.0 * EW_l
                    if avail_w <= 0 or avail_l <= 0:
                        continue

                    ub_nbw = _panelizer_upper_bound_grid(avail_w, board_w, CWi)
                    ub_nbl = _panelizer_upper_bound_grid(avail_l, board_l, CLi)
                    if ub_nbw == 0 or ub_nbl == 0:
                        continue

                    for nbw in range(1, ub_nbw + 1):
                        panel_used_w = nbw * board_w + (nbw - 1) * CWi + 2.0 * EW_w
                        if not _panelizer_almost_le(panel_used_w, WPW):
                            continue
                        for nbl in range(1, ub_nbl + 1):
                            panel_used_l = nbl * board_l + (nbl - 1) * CLi + 2.0 * EW_l
                            if not _panelizer_almost_le(panel_used_l, WPL):
                                continue

                            total_single_pcbs = nbw * nbl * nw * nl
                            util = _panelizer_utilization(total_single_pcbs, SPW, SPL, WPW, WPL)
                            jumbo_multiplier = PANELIZER_JUMBO_MULTIPLIER.get(panel_style, 1)
                            pcbs_per_jumbo = total_single_pcbs * jumbo_multiplier
                            unused_area = panel_area - panel_used_w * panel_used_l
                            rotations_count = (1 if board_rot else 0) + (1 if single_rot else 0)
                            left_margin = EW_w
                            bottom_margin = EW_l
                            right_margin = WPW - panel_used_w
                            top_margin = WPL - panel_used_l
                            mu_score = abs(left_margin - right_margin) + abs(bottom_margin - top_margin)

                            board_origins = []
                            x0, y0 = EW_w, EW_l
                            for j in range(nbl):
                                y = y0 + j * (board_l + CLi)
                                for i in range(nbw):
                                    x = x0 + i * (board_w + CWi)
                                    board_origins.append({"x": x, "y": y, "rotated": board_rot})

                            single_origins = []
                            sx0, sy0 = margin_w_eff, margin_l_eff
                            for jl in range(nl):
                                sy = sy0 + jl * (spl_eff + SLi)
                                for iw in range(nw):
                                    sx = sx0 + iw * (spw_eff + SWi)
                                    single_origins.append({"x": sx, "y": sy, "rotated": single_rot})

                            all_ok = True
                            failure: Optional[str] = None

                            if all_ok:
                                spw_e, spl_e = ((SPL, SPW) if single_rot else (SPW, SPL))
                                single_rects = []
                                for so in single_origins:
                                    sx, sy = so["x"], so["y"]
                                    single_rects.append((sx, sy, sx + spw_e, sy + spl_e))
                                    if sx < 0 or sy < 0 or (sx + spw_e) > board_w or (sy + spl_e) > board_l:
                                        all_ok, failure = False, "Single out of board bounds"
                                        break
                                if all_ok and not _panelizer_pairwise_no_overlap(single_rects):
                                    all_ok, failure = False, "Singles overlap"

                            layouts.append({
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
                            })
    return layouts


def _panelizer_rotation_priority(row: Dict[str, Any]) -> int:
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


def _panelizer_all_rows(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    enabled_sets = {letter for letter in "ABCDE" if cfg.get(f"include_set_{letter}", False)}
    if not enabled_sets:
        return []
    rows: List[Dict[str, Any]] = []
    for style, (pw, pl) in PANELIZER_PANEL_OPTIONS.items():
        if style[:1].upper() not in enabled_sets:
            continue
        rows.extend(_panelizer_enumerate_layouts(cfg, pw, pl, style))
    rows.sort(key=lambda r: (-r["pcbs_per_jumbo"], -r["utilization"], r["objective_key"]))
    return _panelizer_deduplicate_rows(rows)


def _panelizer_summary(rows: List[Dict[str, Any]], cfg: Dict[str, Any]) -> Dict[str, Any]:
    limit = int(cfg.get("limit", 10))
    total = len(rows)
    shown = min(total, limit)
    display_rows = rows[:shown]
    if rows:
        message = f"Found {total} feasible layouts. Showing top {shown} by PCBs per Jumbo."
    else:
        message = "No feasible layouts under current constraints."
    max_pcbs = max((r["pcbs_per_jumbo"] for r in rows), default=None)
    star_message = "Highest PCBs per Jumbo shown with ★" if max_pcbs is not None else ""
    table_attrs = "" if display_rows else 'style="display:none"'
    return {
        "rows": display_rows,
        "message": message,
        "limit": limit,
        "total": total,
        "shown": shown,
        "max_pcbs_per_jumbo": max_pcbs,
        "star_message": star_message,
        "table_attrs": table_attrs,
    }


# ---------------------------------------------------------------------------
# Form parsing & validation
# ---------------------------------------------------------------------------


def _to_float(name: str, default: float) -> float:
    v = request.form.get(name, str(default)).strip()
    try:
        return float(v)
    except ValueError:
        raise ValueError(f"{name} must be a number")


def _to_int(name: str, default: int) -> int:
    v = request.form.get(name, str(default)).strip()
    try:
        return int(v)
    except ValueError:
        raise ValueError(f"{name} must be an integer")


def _make_inputs() -> Inputs:
    payload: dict[str, Any] = {}
    for name, hint in INPUT_TYPE_HINTS.items():
        default = DEFAULTS[name]
        if hint is int:
            payload[name] = _to_int(name, int(default))
        elif hint is float:
            payload[name] = _to_float(name, float(default))
        else:
            payload[name] = request.form.get(name, str(default))
    derived_stack_qty = _stack_qty_lookup(
        payload.get("pcb_thickness"),
        payload.get("cnc_hole_dimension"),
    )
    if derived_stack_qty is not None:
        payload["stack_qty"] = derived_stack_qty
    else:
        payload["stack_qty"] = max(1, int(payload.get("stack_qty", 1)))
    return Inputs(**payload)


def _make_params() -> Params:
    payload: dict[str, Any] = {}
    for name, hint in PARAM_TYPE_HINTS.items():
        default = DEFAULTS.get(name)
        if hint is float and default is not None:
            payload[name] = _to_float(name, float(default))
        elif hint is int and default is not None:
            payload[name] = _to_int(name, int(default))
        else:
            value = default
            if isinstance(value, dict):
                value = value.copy()
            payload[name] = value

    selected_choices = {
        field.name: request.form.get(field.name, DEFAULTS.get(field.name))
        for field in PRICED_FIELDS
    }

    def _apply_override(price_field: str, map_key: str, selected: str | None, err_msg: str) -> None:
        raw = request.form.get(price_field)
        if raw in (None, ""):
            return
        try:
            value = float(raw)
        except ValueError:
            raise ValueError(err_msg)
        if not selected:
            return
        price_map = payload.get(map_key)
        if price_map is None:
            price_map = {}
            payload[map_key] = price_map
        price_map[selected] = value

    for field in PRICED_FIELDS:
        form_key = field.price_field
        _apply_override(form_key, field.map_key, selected_choices.get(field.name), field.error)
    return Params(**payload)


def _validate(d: dict[str, Any]) -> list[str]:
    errs = []
    if not (1 <= d["layers"] <= 40):
        errs.append("Layers must be 1–40.")
    if d["panel_boards"] < 1:
        errs.append("Boards per panel must be >= 1.")
    if d.get("stack_qty", 1) < 1:
        errs.append("Stack quantity must be >= 1.")
    if d.get("cnc_pth_holes", 0) < 0:
        errs.append("CNC PTH holes must be >= 0.")
    if d.get("cutting_cost", 0.0) < 0:
        errs.append("Cutting cost must be >= 0.")
    if d.get("routing_length", 0.0) < 0:
        errs.append("Routing length must be >= 0.")
    if d.get("stamping_cost", 0.0) < 0:
        errs.append("Stamping cost must be >= 0.")
    if d.get("post_process_cost", 0.0) < 0:
        errs.append("Post Process cost must be >= 0.")
    return errs


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------


@app.route("/", methods=["GET", "POST"])
def index():
    error_msgs, result = [], None
    resolved_inputs: Inputs | None = None

    panelizer_error = None
    panelizer_cfg = _panelizer_default_config()
    panelizer_rows: List[Dict[str, Any]] = []
    panelizer_summary = None
    panelizer_source = request.values
    try:
        panelizer_cfg = _panelizer_config(panelizer_source)
        panelizer_rows = _panelizer_all_rows(panelizer_cfg)
        panelizer_summary = _panelizer_summary(panelizer_rows, panelizer_cfg)
    except Exception as exc:
        panelizer_error = str(exc)

    computed_panel_boards: int | None = None
    if panelizer_summary:
        max_pcbs = panelizer_summary.get("max_pcbs_per_jumbo")
        if max_pcbs is not None:
            computed_panel_boards = max(1, int(max_pcbs))

    if request.method == "POST":
        try:
            inp = _make_inputs()
            if computed_panel_boards is not None:
                inp.panel_boards = computed_panel_boards
            resolved_inputs = inp
            errs = _validate(vars(inp))
            if errs:
                error_msgs = errs
            else:
                prm = _make_params()
                result = price_quote(inp, prm)
                persist_panelizer = None if panelizer_error else panelizer_cfg
                _persist_defaults(inp, prm, persist_panelizer)
        except Exception as e:
            error_msgs = [str(e)]
            result = None

    param_defaults = {
        name: DEFAULTS[name]
        for name, hint in PARAM_TYPE_HINTS.items()
        if hint in (int, float) and name in DEFAULTS
    }
    form_defaults = {
        name: DEFAULTS[name]
        for name in INPUT_FIELD_NAMES
        if name in DEFAULTS
    }
    form_values = {k: request.form.get(k, str(v)) for k, v in form_defaults.items()}
    if resolved_inputs is not None:
        form_values["stack_qty"] = str(resolved_inputs.stack_qty)
        form_values["panel_boards"] = str(resolved_inputs.panel_boards)
    param_values = {k: request.form.get(k, str(v)) for k, v in param_defaults.items()}

    selected_choices = {
        field.name: form_values.get(field.name, str(DEFAULTS.get(field.name, "")))
        for field in PRICED_FIELDS
    }

    def _form_price_value(field_name: str, defaults_map: dict[str, Any], selected: str) -> str:
        raw = request.form.get(field_name)
        if raw not in (None, ""):
            return raw
        default_value = defaults_map.get(selected)
        return "" if default_value in (None, "") else str(default_value)

    price_value_kwargs = {}
    for field in PRICED_FIELDS:
        defaults_map = PRICED_DEFAULT_MAPS[field.name]
        price_value_kwargs[f"{field.price_field}_value"] = _form_price_value(
            field.price_field, defaults_map, selected_choices[field.name]
        )

    if resolved_inputs is None and computed_panel_boards is not None:
        form_values["panel_boards"] = str(computed_panel_boards)

    return render_template(
        "index_qp.html",
        defaults=form_defaults,
        values=form_values,
        params_defaults=param_defaults,
        params_values=param_values,
        pcb_thickness_options=PCB_THICKNESS_OPTIONS,
        cnc_hole_dimension_options=CNC_HOLE_DIMENSION_OPTIONS,
        error_msgs=error_msgs,
        result=result,
        priced_fields=PRICED_FIELDS,
        priced_options=SELECT_OPTIONS,
        priced_costs=PRICED_DEFAULT_MAPS,
        priced_client_config=[{"name": field.name, "priceField": field.price_field} for field in PRICED_FIELDS],
        stack_qty_map=DEFAULTS.get("stack_qty_map", {}),
        panelizer_values=panelizer_cfg,
        panelizer_summary=panelizer_summary,
        panelizer_rows=panelizer_rows,
        panelizer_error=panelizer_error,
        **price_value_kwargs,
    )


@app.route("/lt.png")
@app.route("/favicon.ico")
def serve_icon():
    return send_file(ICON_PATH, mimetype="image/png")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("DEBUG", "0") in ["1", "true", "True"]
    app.run(host=host, port=port, debug=debug)
