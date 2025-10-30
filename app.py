#!/usr/bin/env python3
"""
Web UI for brute-force PCB panelization.

- Single file. Standard library only.
- Edit all parameters in the form. Defaults pre-filled.
- Press "Calculate" to enumerate ALL feasible layouts.
- Results sorted by utilization (desc). Primary objective and tie-breakers shown.

Run:
  python webui_pcb_panelizer.py
Open:
  http://127.0.0.1:8000
"""
import os
from wsgiref.simple_server import make_server
from urllib.parse import parse_qs
from html import escape
import json
import math
from typing import Dict, Tuple, List, Optional

# ------------------------------ Core Solver ----------------------------------

PANEL_OPTIONS: Dict[str, Tuple[float, float]] = {
    "A1": (520.5, 622.5),    "A2": (415.0, 622.5),    "A3": (347.0, 622.5),    "A4": (520.5, 415.0),
    "B1": (546.0, 622.5),    "B2": (415.0, 622.5),    "B3": (415.0, 546.0),    "B4": (364.0, 622.5),
    "C1": (546.0, 647.5),    "C2": (431.6, 647.5),    "C3": (431.6, 546.0),    "C4": (364.0, 647.5),
    "D1": (520.5, 694.0),    "D2": (415.0, 694.0),    "D3": (416.4, 622.5),    "D4": (365.0, 622.5),
    "E1": (546.0, 728.0),    "E2": (431.5, 728.0),    "E3": (436.8, 647.5),    "E4": (384.1, 647.5),
}

JUMBO_MULTIPLIER: Dict[str, int] = {
    "A1": 4,    "A2": 5,    "A3": 6,    "A4": 6,
    "B1": 4,    "B2": 5,    "B3": 6,    "B4": 6,
    "C1": 4,    "C2": 5,    "C3": 6,    "C4": 6,
    "D1": 7,    "D2": 9,    "D3": 10,    "D4": 11,
    "E1": 7,    "E2": 9,    "E3": 10,    "E4": 11,
}

def default_config() -> Dict[str, float]:
    return {
        "customer_board_width_max": 350.0,
        "customer_board_length_max": 400.0,
        "customer_board_width_min": 80.0,
        "customer_board_length_min": 80.0,
        "single_pcb_width_max": 52.0,
        "single_pcb_length_max": 76.2,
        "panel_edge_margin_w": 5.0,
        "panel_edge_margin_l": 5.0,
        "board_edge_margin_w": 5.0,
        "board_edge_margin_l": 0.0,
        "inter_board_gap_w": 2.0,
        "inter_board_gap_l": 2.0,
        "inter_single_gap_w": 0.0,
        "inter_single_gap_l": 0.0,
        "allow_rotate_board": True,
        "allow_rotate_single_pcb": True,
        "kerf_allowance": 0.0,
        "limit": 20,  # UI-only: max rows to display
        "include_set_A": True,
        "include_set_B": True,
        "include_set_C": True,
        "include_set_D": False,
        "include_set_E": False,
    }

def _almost_le(a: float, b: float, eps: float = 1e-9) -> bool:
    return a <= b + eps

def _almost_ge(a: float, b: float, eps: float = 1e-9) -> bool:
    return a + eps >= b

def _rects_overlap_1d(a0: float, a1: float, b0: float, b1: float, eps: float = 1e-9) -> bool:
    return (a0 < b1 - eps) and (b0 < a1 - eps)

def _pairwise_no_overlap(rects: List[Tuple[float, float, float, float]], eps: float = 1e-9) -> bool:
    n = len(rects)
    for i in range(n):
        xi0, yi0, xi1, yi1 = rects[i]
        for j in range(i + 1, n):
            xj0, yj0, xj1, yj1 = rects[j]
            if _rects_overlap_1d(xi0, xi1, xj0, xj1, eps) and _rects_overlap_1d(yi0, yi1, yj0, yj1, eps):
                return False
    return True

def _upper_bound_grid(max_len: float, item: float, gap: float) -> int:
    if item <= 0:
        return 0
    return max(0, int(math.floor((max_len + gap) / (item + gap))))

def _utilization(total_single_pcbs: int, spw: float, spl: float, wpw: float, wpl: float) -> float:
    return (total_single_pcbs * spw * spl) / (wpw * wpl) if wpw > 0 and wpl > 0 else 0.0

def enumerate_layouts(cfg: Dict[str, float], panel_w: float, panel_l: float, panel_style: str) -> List[Dict]:
    # Extract
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

    # Inflate gaps
    CWi, CLi = CW + kerf, CL + kerf
    SWi, SLi = SW + kerf, SL + kerf

    panel_area = WPW * WPL

    layouts: List[Dict] = []
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

            ub_nw = _upper_bound_grid(max_inner_w, spw_eff, SWi)
            ub_nl = _upper_bound_grid(max_inner_l, spl_eff, SLi)
            if ub_nw == 0 or ub_nl == 0:
                continue

            for nw in range(1, ub_nw + 1):
                single_grid_w = nw * spw_eff + (nw - 1) * SWi
                if not _almost_le(single_grid_w, max_inner_w):
                    continue
                for nl in range(1, ub_nl + 1):
                    single_grid_l = nl * spl_eff + (nl - 1) * SLi
                    if not _almost_le(single_grid_l, max_inner_l):
                        continue

                    board_w = single_grid_w + 2.0 * margin_w_eff
                    board_l = single_grid_l + 2.0 * margin_l_eff
                    if not _almost_ge(board_w, CBW_min_eff) or not _almost_ge(board_l, CBL_min_eff):
                        continue
                    avail_w = WPW - 2.0 * EW_w
                    avail_l = WPL - 2.0 * EW_l
                    if avail_w <= 0 or avail_l <= 0:
                        continue

                    ub_nbw = _upper_bound_grid(avail_w, board_w, CWi)
                    ub_nbl = _upper_bound_grid(avail_l, board_l, CLi)
                    if ub_nbw == 0 or ub_nbl == 0:
                        continue

                    for nbw in range(1, ub_nbw + 1):
                        panel_used_w = nbw * board_w + (nbw - 1) * CWi + 2.0 * EW_w
                        if not _almost_le(panel_used_w, WPW):
                            continue
                        for nbl in range(1, ub_nbl + 1):
                            panel_used_l = nbl * board_l + (nbl - 1) * CLi + 2.0 * EW_l
                            if not _almost_le(panel_used_l, WPL):
                                continue

                            total_single_pcbs = nbw * nbl * nw * nl
                            util = _utilization(total_single_pcbs, SPW, SPL, WPW, WPL)
                            jumbo_multiplier = JUMBO_MULTIPLIER.get(panel_style, 1)
                            pcbs_per_jumbo = total_single_pcbs * jumbo_multiplier
                            unused_area = panel_area - panel_used_w * panel_used_l
                            rotations_count = (1 if board_rot else 0) + (1 if single_rot else 0)
                            left_margin = EW_w
                            bottom_margin = EW_l
                            right_margin = WPW - panel_used_w
                            top_margin = WPL - panel_used_l
                            mu_score = abs(left_margin - right_margin) + abs(bottom_margin - top_margin)

                            # Placements (for first N rows we display summary; full JSON available)
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

                            # Validation
                            all_ok = True
                            failure: Optional[str] = None
                            # Board limit under rotation
                            if not _almost_le(board_w, (CBL if board_rot else CBW)):  # width
                                all_ok, failure = False, "Board width exceeds limit"
                            if all_ok and not _almost_le(board_l, (CBW if board_rot else CBL)):  # length
                                all_ok, failure = False, "Board length exceeds limit"
                            if all_ok and not _almost_ge(board_w, CBW_min_eff):
                                all_ok, failure = False, "Board width below minimum"
                            if all_ok and not _almost_ge(board_l, CBL_min_eff):
                                all_ok, failure = False, "Board length below minimum"
                            # Board rectangles
                            board_rects = []
                            for bo in board_origins:
                                x, y = bo["x"], bo["y"]
                                board_rects.append((x, y, x + board_w, y + board_l))
                                if x < 0 or y < 0 or (x + board_w) > WPW or (y + board_l) > WPL:
                                    all_ok, failure = False, "Board out of panel bounds"
                                    break
                            if all_ok and not _pairwise_no_overlap(board_rects):
                                all_ok, failure = False, "Boards overlap"
                            # Singles inside local board
                            if all_ok:
                                spw_e, spl_e = ((SPL, SPW) if single_rot else (SPW, SPL))
                                single_rects = []
                                for so in single_origins:
                                    sx, sy = so["x"], so["y"]
                                    single_rects.append((sx, sy, sx + spw_e, sy + spl_e))
                                    if sx < 0 or sy < 0 or (sx + spw_e) > board_w or (sy + spl_e) > board_l:
                                        all_ok, failure = False, "Single out of board bounds"
                                        break
                                if all_ok and not _pairwise_no_overlap(single_rects):
                                    all_ok, failure = False, "Singles overlap"

                            layouts.append({
                                "total_single_pcbs": total_single_pcbs,
                                "utilization": util,
                                "unused_area": unused_area,
                                "nbw": nbw, "nbl": nbl,
                                "nw": nw, "nl": nl,
                                "board_rot": board_rot, "single_rot": single_rot,
                                "board_w": board_w, "board_l": board_l,
                                "panel_used_w": panel_used_w, "panel_used_l": panel_used_l,
                                "panel_style": panel_style,
                                "panel_width": WPW,
                                "panel_length": WPL,
                                "pcbs_per_jumbo": pcbs_per_jumbo,
                                "margins": {"left": left_margin, "right": right_margin,
                                            "bottom": bottom_margin, "top": top_margin},
                                "margin_uniformity": mu_score,
                                "rotations_count": rotations_count,
                                "placements": {
                                    "boards": board_origins,
                                    "singles_per_board": single_origins
                                },
                                "all_constraints_satisfied": all_ok,
                                "first_failure": failure,
                                # Primary objective sort key (for reference)
                                "objective_key": (
                                    -total_single_pcbs,          # maximize
                                    -util,                       # maximize
                                    unused_area,                 # minimize
                                    mu_score,                    # minimize
                                    rotations_count,             # minimize
                                ),
                            })

    return layouts

# ------------------------------ Web Utilities --------------------------------

ICON_FILENAME = "lt.png"
ICON_PATH = os.path.join(os.path.dirname(__file__), ICON_FILENAME)
CSS_FILENAME = "panelizer.css"
CSS_PATH = os.path.join(os.path.dirname(__file__), "static", CSS_FILENAME)

def parse_bool(v: str) -> bool:
    if isinstance(v, str):
        return v.lower() in ("1", "true", "on", "yes")
    return bool(v)


def parse_checkbox(qs: dict, key: str, default: bool) -> bool:
    if key in qs:
        values = qs.get(key, [])
        raw = values[0] if values else "on"
        raw = raw if raw is not None else "on"
        return parse_bool(raw if raw != "" else "on")
    if not qs:
        return default
    return False

def parse_float(qs: dict, key: str, default: float) -> float:
    try:
        return float(qs.get(key, [default])[0])
    except Exception:
        return default

def parse_int(qs: dict, key: str, default: int) -> int:
    try:
        return int(qs.get(key, [default])[0])
    except Exception:
        return default

def parse_cfg(qs: dict) -> Dict[str, float]:
    d = default_config()
    d["customer_board_width_max"]  = parse_float(qs, "CBW", d["customer_board_width_max"])
    d["customer_board_length_max"] = parse_float(qs, "CBL", d["customer_board_length_max"])
    d["customer_board_width_min"]  = parse_float(qs, "CBWM", d["customer_board_width_min"])
    d["customer_board_length_min"] = parse_float(qs, "CBLM", d["customer_board_length_min"])
    d["single_pcb_width_max"]  = parse_float(qs, "SPW", d["single_pcb_width_max"])
    d["single_pcb_length_max"] = parse_float(qs, "SPL", d["single_pcb_length_max"])
    d["panel_edge_margin_w"] = parse_float(qs, "EW_w", d["panel_edge_margin_w"])
    d["panel_edge_margin_l"] = parse_float(qs, "EW_l", d["panel_edge_margin_l"])
    d["board_edge_margin_w"] = parse_float(qs, "BMW", d["board_edge_margin_w"])
    d["board_edge_margin_l"] = parse_float(qs, "BML", d["board_edge_margin_l"])
    d["inter_board_gap_w"] = parse_float(qs, "CW", d["inter_board_gap_w"])
    d["inter_board_gap_l"] = parse_float(qs, "CL", d["inter_board_gap_l"])
    d["inter_single_gap_w"] = parse_float(qs, "SW", d["inter_single_gap_w"])
    d["inter_single_gap_l"] = parse_float(qs, "SL", d["inter_single_gap_l"])
    d["allow_rotate_board"] = parse_checkbox(qs, "ARB", d["allow_rotate_board"])
    d["allow_rotate_single_pcb"] = parse_checkbox(qs, "ARS", d["allow_rotate_single_pcb"])
    d["kerf_allowance"] = parse_float(qs, "KERF", d["kerf_allowance"])
    d["limit"] = parse_int(qs, "LIMIT", d["limit"])
    d["include_set_A"] = parse_checkbox(qs, "SET_A", d["include_set_A"])
    d["include_set_B"] = parse_checkbox(qs, "SET_B", d["include_set_B"])
    d["include_set_C"] = parse_checkbox(qs, "SET_C", d["include_set_C"])
    d["include_set_D"] = parse_checkbox(qs, "SET_D", d["include_set_D"])
    d["include_set_E"] = parse_checkbox(qs, "SET_E", d["include_set_E"])
    return d

def input_field(name, label, value, step="0.1"):
    return f"""<div>
<label for="{name}">{escape(label)}</label>
<input type="number" step="{step}" name="{name}" id="{name}" value="{value}"/>
</div>"""

def checkbox_field(name, label, checked: bool):
    return f"""<div>
<label for="{name}">{escape(label)}</label>
<input type="checkbox" name="{name}" id="{name}" {"checked" if checked else ""}/>
</div>"""

def _rotation_priority(row: Dict) -> int:
    board_rot = row.get("board_rot", False)
    single_rot = row.get("single_rot", False)
    if not board_rot and not single_rot:
        return 0
    if board_rot and not single_rot:
        return 1
    if not board_rot and single_rot:
        return 2
    return 3

def deduplicate_rows(rows: List[Dict]) -> List[Dict]:
    seen_order: List[Tuple[str, int, int, int, int, int]] = []
    best: Dict[Tuple[str, int, int, int, int, int], Dict] = {}
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
        if _rotation_priority(row) < _rotation_priority(current):
            best[key] = row

    return [best[k] for k in seen_order]

def page(cfg: Dict[str, float], rows: List[Dict]) -> str:
    # Summary
    total = len(rows)
    max_pcbs_jumbo = max((r["pcbs_per_jumbo"] for r in rows), default=None)

    # HTML
    h = []
    h.append("<html><head><meta charset='utf-8'><title>PCB Panelizer</title>")
    h.append("<link rel='icon' type='image/png' href='/lt.png'>")
    h.append(f"<link rel='stylesheet' href='/static/{CSS_FILENAME}'></head><body>")
    h.append("<h1>PCB Panelizer by LT</h1>")
#    h.append("<p class='note'>Edit parameters. Press Calculate. Results ranked by PCBs per Jumbo.</p>")
    # Form
    h.append("<form method='GET'>")

    h.append("<div class='fieldset-row'>")

    # Single PCB (leftmost)
    h.append("<fieldset><legend>Single PCB</legend>")
    h.append(input_field("SPW", "Single width (SPW, mm)", cfg["single_pcb_width_max"]))
    h.append(input_field("SPL", "Single length (SPL, mm)", cfg["single_pcb_length_max"]))
    h.append(checkbox_field("ARS", "Allow rotate single", cfg["allow_rotate_single_pcb"]))
    h.append("</fieldset>")

    # Panel margins
    h.append("<fieldset><legend>Working Panel Margins</legend>")
    h.append(input_field("EW_w", "Panel edge margin width (EW_w, mm)", cfg["panel_edge_margin_w"]))
    h.append(input_field("EW_l", "Panel edge margin length (EW_l, mm)", cfg["panel_edge_margin_l"]))
    h.append("<div class='checkbox-group'>")
    h.append("<span>Panel sets</span>")
    panel_set_labels = {
        "A": "A: 1245 x 1041",
        "B": "B: 1245 x 1092",
        "C": "C: 1295 x 1092",
        "D": "D: 1245 x 2082",
        "E": "E: 1295 x 2184",
    }
    for letter in "ABCDE":
        name = f"SET_{letter}"
        cfg_key = f"include_set_{letter}"
        checked_attr = "checked" if bool(cfg.get(cfg_key, False)) else ""
        h.append(
            f"<label class='panel-set-option'>"
            f"<input type='checkbox' name='{name}' id='{name}' {checked_attr}/>"
            f"<span>{panel_set_labels.get(letter, letter)}</span>"
            "</label>"
        )
    h.append("</div>")
    h.append("</fieldset>")

    # Board edge margins (auxiliary rails)
    h.append("<fieldset><legend>Board Edge Margins</legend>")
    h.append(input_field("BMW", "Board edge margin width (BMW, mm)", cfg["board_edge_margin_w"]))
    h.append(input_field("BML", "Board edge margin length (BML, mm)", cfg["board_edge_margin_l"]))
    h.append("</fieldset>")

    # Customer board
    h.append("<fieldset><legend>Customer Board Limits</legend>")
    h.append(input_field("CBW", "Max board width (CBW, mm)", cfg["customer_board_width_max"]))
    h.append(input_field("CBL", "Max board length (CBL, mm)", cfg["customer_board_length_max"]))
    h.append(input_field("CBWM", "Min board width (CBWM, mm)", cfg["customer_board_width_min"]))
    h.append(input_field("CBLM", "Min board length (CBLM, mm)", cfg["customer_board_length_min"]))
    h.append(checkbox_field("ARB", "Allow rotate board", cfg["allow_rotate_board"]))
    h.append("</fieldset>")

    # V-Cut Gaps
    h.append("<fieldset><legend>Gaps</legend>")
    h.append(input_field("CW", "Inter-board gap W (CW, mm)", cfg["inter_board_gap_w"]))
    h.append(input_field("CL", "Inter-board gap L (CL, mm)", cfg["inter_board_gap_l"]))
    h.append(input_field("SW", "Inter-single gap W (SW, mm)", cfg["inter_single_gap_w"]))
    h.append(input_field("SL", "Inter-single gap L (SL, mm)", cfg["inter_single_gap_l"]))
    h.append(input_field("KERF", "Kerf (adds to all gaps, mm)", cfg["kerf_allowance"], step="0.1"))
    h.append("</fieldset>")

    h.append("</div>")

    # Controls
    h.append("<div class='controls'>")
    h.append(input_field("LIMIT", "Max rows", int(cfg.get("limit", 10)), step="1"))
    h.append("<button type='submit'>Calculate</button>")
    if max_pcbs_jumbo is not None:
        h.append("<span class='badge'>Highest PCBs per Jumbo shown with ★</span>")
    h.append("</div>")
    h.append("</form>")

    # Results
    if rows:
        h.append(f"<p class='small'>Found {total} feasible layouts. Showing top {min(total, cfg['limit'])} by PCBs per Jumbo.</p>")
        h.append("<table>")
        h.append("<tr>"
                 "<th class='l'>Rank</th>"
                 "<th>PCBs/Jumbo</th>"
                 "<th>PCBs/Panel</th>"
                 "<th>Panel WxL</th>"
                 "<th>Board WxL</th>"
                 "<th>Board size (mm)</th>"
                 "<th>Panel style</th>"
                 "<th>Panel size (mm)</th>"
                 "<th>Utilization</th>"
                 "<th>Rotation</th>"
                 "</tr>")
        for idx, r in enumerate(rows[: int(cfg["limit"])]):
            star = " ★" if max_pcbs_jumbo is not None and r["pcbs_per_jumbo"] == max_pcbs_jumbo else ""
            util = f"{r['utilization'] * 100:.2f}%"
            board_sz = f"{r['board_w']:.1f}×{r['board_l']:.1f}"
            panel_style = r['panel_style']
            panel_size = f"{r['panel_width']:.1f}×{r['panel_length']:.1f}"
            rot = ("B" if r["board_rot"] else "") + ("S" if r["single_rot"] else "")
            rot = rot if rot else "—"
            h.append("<tr>")
            h.append(f"<td class='l'>{idx+1}{star}</td>")
            h.append(f"<td>{r['pcbs_per_jumbo']}</td>")
            h.append(f"<td>{r['total_single_pcbs']}</td>")
            h.append(f"<td>{r['nbw']}×{r['nbl']}</td>")
            h.append(f"<td>{r['nw']}×{r['nl']}</td>")
            h.append(f"<td>{board_sz}</td>")
            h.append(f"<td>{panel_style}</td>")
            h.append(f"<td>{panel_size}</td>")
            h.append(f"<td>{util}</td>")
            h.append(f"<td>{rot}</td>")
            h.append("</tr>")
            # Details row
            # details = {
            #     "margins": r["margins"],
            #     "margin_uniformity": r["margin_uniformity"],
            #     "all_constraints_satisfied": r["all_constraints_satisfied"],
            #     "first_failure": r["first_failure"],
            # }
            # h.append(
            #     f"<tr><td colspan='10' class='l'><details><summary>Details</summary>"
            #     f"<pre>{escape(json.dumps(details, indent=2))}</pre></details></td></tr>"
            # )
        h.append("</table>")
    else:
        h.append("<p class='small'>No feasible layouts under current constraints.</p>")

    h.append("</body></html>")
    return "".join(h)

# ------------------------------ WSGI Handler ---------------------------------

def app(environ, start_response):
    try:
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "") or "/"
        if path in (f"/{ICON_FILENAME}", "/favicon.ico"):
            try:
                with open(ICON_PATH, "rb") as fh:
                    data = fh.read()
            except FileNotFoundError:
                start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8"),
                                                 ("Content-Length", "0")])
                return [b""]
            headers = [("Content-Type", "image/png"), ("Content-Length", str(len(data)))]
            start_response("200 OK", headers)
            if method == "HEAD":
                return [b""]
            return [data]

        if path == f"/static/{CSS_FILENAME}":
            try:
                with open(CSS_PATH, "rb") as fh:
                    data = fh.read()
            except FileNotFoundError:
                start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8"),
                                                 ("Content-Length", "0")])
                return [b""]
            headers = [("Content-Type", "text/css; charset=utf-8"), ("Content-Length", str(len(data)))]
            start_response("200 OK", headers)
            if method == "HEAD":
                return [b""]
            return [data]

        if method == "POST":
            size = int(environ.get("CONTENT_LENGTH", "0") or 0)
            body = environ["wsgi.input"].read(size).decode("utf-8") if size > 0 else ""
            qs = parse_qs(body)
        else:
            qs = parse_qs(environ.get("QUERY_STRING", ""))

        cfg = parse_cfg(qs)

        # Compute across all panel styles
        all_rows: List[Dict] = []
        enabled_sets = {letter for letter in "ABCDE" if cfg.get(f"include_set_{letter}", False)}
        for style, (pw, pl) in PANEL_OPTIONS.items():
            # Only evaluate panel styles whose set letter is enabled in the UI.
            if style[:1].upper() not in enabled_sets:
                continue
            all_rows.extend(enumerate_layouts(cfg, pw, pl, style))
        # Sort by PCBs per Jumbo desc, then utilization/objective for stability
        all_rows.sort(key=lambda r: (-r["pcbs_per_jumbo"], -r["utilization"], r["objective_key"]))
        all_rows = deduplicate_rows(all_rows)

        html = page(cfg, all_rows)
        data = html.encode("utf-8")
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"),
                                  ("Content-Length", str(len(data)))])
        return [data]
    except Exception as e:
        msg = f"<pre>{escape(repr(e))}</pre>"
        data = msg.encode("utf-8")
        start_response("500 Internal Server Error", [("Content-Type", "text/html; charset=utf-8"),
                                                     ("Content-Length", str(len(data)))])
        return [data]

# --------------------------------- Main --------------------------------------

if __name__ == "__main__":
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "8080"))
    with make_server(host, port, app) as httpd:
        print(f"Serving on http://{host}:{port}")
        httpd.serve_forever()
