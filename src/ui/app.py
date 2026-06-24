"""
Gradio UI for SupplyIQ: tabs for each optimization domain (replenishment,
routing, network) plus a copilot chat tab for natural-language
explain/what-if queries against any previously-solved plan.
"""
from __future__ import annotations

import json
import os

import gradio as gr
import httpx

API_BASE_URL = os.environ.get("SUPPLYIQ_API_URL", "http://localhost:8000")

_SAMPLE_REPLENISHMENT = json.dumps(
    {
        "sku_locations": [
            {
                "sku": "SKU-001", "location_id": "WH-EAST", "current_stock": 120,
                "daily_demand_forecast": 25.0, "demand_std_dev": 5.0, "lead_time_days": 7,
                "unit_cost": 12.50, "holding_cost_rate": 0.2, "order_cost": 75.0,
                "service_level_target": 0.95,
            },
            {
                "sku": "SKU-002", "location_id": "WH-EAST", "current_stock": 30,
                "daily_demand_forecast": 10.0, "demand_std_dev": 3.0, "lead_time_days": 14,
                "unit_cost": 40.0, "holding_cost_rate": 0.25, "order_cost": 120.0,
                "service_level_target": 0.99,
            },
        ],
        "budget_constraint": None,
    },
    indent=2,
)

_SAMPLE_ROUTING = json.dumps(
    {
        "depot": {"latitude": 40.7128, "longitude": -74.0060},
        "stops": [
            {"location": {"latitude": 40.73, "longitude": -73.99}, "demand_units": 5},
            {"location": {"latitude": 40.75, "longitude": -73.97}, "demand_units": 8},
            {"location": {"latitude": 40.71, "longitude": -74.02}, "demand_units": 3},
        ],
        "vehicles": [
            {"vehicle_id": "V1", "capacity_units": 20, "start_location": {"latitude": 40.7128, "longitude": -74.0060}}
        ],
        "average_speed_kmh": 35,
    },
    indent=2,
)

_SAMPLE_NETWORK = json.dumps(
    {
        "warehouses": [
            {"warehouse_id": "WH-1", "capacity_units": 500},
            {"warehouse_id": "WH-2", "capacity_units": 300},
        ],
        "demand_locations": [
            {"location_id": "L1", "demand_units": 400},
            {"location_id": "L2", "demand_units": 200},
        ],
        "shipping_lanes": [
            {"warehouse_id": "WH-1", "location_id": "L1", "cost_per_unit": 2.0},
            {"warehouse_id": "WH-1", "location_id": "L2", "cost_per_unit": 3.5},
            {"warehouse_id": "WH-2", "location_id": "L1", "cost_per_unit": 1.5},
            {"warehouse_id": "WH-2", "location_id": "L2", "cost_per_unit": 2.5},
        ],
    },
    indent=2,
)


def _post(path: str, payload: dict) -> tuple[bool, dict | str]:
    try:
        resp = httpx.post(f"{API_BASE_URL}{path}", json=payload, timeout=60)
        resp.raise_for_status()
        return True, resp.json()
    except httpx.RequestError as exc:
        return False, f"Could not reach API: {exc}"
    except httpx.HTTPStatusError as exc:
        return False, f"API error: {exc.response.text[:400]}"


def solve_replenishment(payload_json: str) -> tuple[str, str]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        return f"Invalid JSON: {exc}", ""
    ok, result = _post("/replenishment/solve", payload)
    if not ok:
        return str(result), ""

    lines = [
        f"Plan `{result['plan_id']}` - method: {result['solve_method']} - total cost: ${result['total_order_cost']:.2f}\n"
    ]
    for rec in result["recommendations"]:
        flag = "REORDER NOW" if rec["should_reorder_now"] else "ok"
        lines.append(
            f"**{rec['sku']} @ {rec['location_id']}** [{flag}] - ROP={rec['reorder_point']:.0f}, "
            f"EOQ={rec['economic_order_quantity']:.0f}, qty={rec['recommended_order_quantity']}, "
            f"days of supply={rec['days_of_supply_remaining']:.1f}\n  {' '.join(rec['reasoning'])}"
        )
    return "\n\n".join(lines), result["plan_id"]


def solve_routing(payload_json: str) -> tuple[str, str]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        return f"Invalid JSON: {exc}", ""
    ok, result = _post("/routing/solve", payload)
    if not ok:
        return str(result), ""

    lines = [
        f"Plan `{result['plan_id']}` - method: {result['solve_method']} - total distance: {result['total_distance_km']:.1f} km\n"
    ]
    for route in result["routes"]:
        stop_ids = ", ".join(s["stop_id"][:8] for s in route["steps"])
        lines.append(
            f"**{route['vehicle_id']}** - {len(route['steps'])} stops ({stop_ids}), "
            f"{route['total_distance_km']:.1f} km, {route['load_utilization_pct']:.0f}% load"
        )
    if result["unassigned_stop_ids"]:
        lines.append(f"\nWARNING: Unassigned stops: {len(result['unassigned_stop_ids'])}")
    return "\n\n".join(lines), result["plan_id"]


def solve_network(payload_json: str) -> tuple[str, str]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        return f"Invalid JSON: {exc}", ""
    ok, result = _post("/network/solve", payload)
    if not ok:
        return str(result), ""

    lines = [f"Plan `{result['plan_id']}` - method: {result['solve_method']} - total cost: ${result['total_cost']:.2f}\n"]
    for alloc in result["allocations"]:
        lines.append(f"{alloc['warehouse_id']} -> {alloc['location_id']}: {alloc['units_shipped']} units (${alloc['cost']:.2f})")
    if result["unmet_demand_units"] > 0:
        lines.append(f"\nWARNING: Unmet demand: {result['unmet_demand_units']} units")
    return "\n\n".join(lines), result["plan_id"]


def ask_copilot(question: str, plan_id: str, domain: str) -> str:
    if not plan_id:
        return "Solve a plan first, then ask about it (the plan ID auto-fills after solving)."
    if not question:
        return "Enter a question."

    ok, result = _post("/copilot/ask", {"question": question, "plan_id": plan_id, "domain": domain})
    if not ok:
        return str(result)

    lines = [f"**Intent:** {result['intent']}\n", result["answer_text"]]
    if result.get("modifications_applied"):
        lines.append("\n**Modifications applied:**")
        for mod in result["modifications_applied"]:
            lines.append(f"- `{mod['field_path']}` -> `{mod['new_value']}` ({mod['rationale']})")
    if result.get("new_plan_id"):
        lines.append(f"\nRe-solved as new plan: `{result['new_plan_id']}`")
    return "\n".join(lines)


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="SupplyIQ", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# SupplyIQ - Supply Chain Optimization Copilot")
        gr.Markdown(
            "Replenishment, vehicle routing, and network optimization - "
            "exact OR-Tools solvers with heuristic fallback, plus a natural-language copilot."
        )

        plan_id_state = gr.State("")
        domain_state = gr.State("replenishment")

        with gr.Tab("Replenishment"):
            repl_input = gr.Code(value=_SAMPLE_REPLENISHMENT, language="json", label="Request (JSON)", lines=15)
            repl_btn = gr.Button("Solve", variant="primary")
            repl_output = gr.Markdown()
            repl_plan_id = gr.Textbox(label="Plan ID (auto-filled)", interactive=False)
            repl_btn.click(fn=solve_replenishment, inputs=repl_input, outputs=[repl_output, repl_plan_id])
            repl_plan_id.change(fn=lambda pid: (pid, "replenishment"), inputs=repl_plan_id, outputs=[plan_id_state, domain_state])

        with gr.Tab("Vehicle Routing"):
            route_input = gr.Code(value=_SAMPLE_ROUTING, language="json", label="Request (JSON)", lines=15)
            route_btn = gr.Button("Solve", variant="primary")
            route_output = gr.Markdown()
            route_plan_id = gr.Textbox(label="Plan ID (auto-filled)", interactive=False)
            route_btn.click(fn=solve_routing, inputs=route_input, outputs=[route_output, route_plan_id])
            route_plan_id.change(fn=lambda pid: (pid, "routing"), inputs=route_plan_id, outputs=[plan_id_state, domain_state])

        with gr.Tab("Network Optimization"):
            net_input = gr.Code(value=_SAMPLE_NETWORK, language="json", label="Request (JSON)", lines=15)
            net_btn = gr.Button("Solve", variant="primary")
            net_output = gr.Markdown()
            net_plan_id = gr.Textbox(label="Plan ID (auto-filled)", interactive=False)
            net_btn.click(fn=solve_network, inputs=net_input, outputs=[net_output, net_plan_id])
            net_plan_id.change(fn=lambda pid: (pid, "network"), inputs=net_plan_id, outputs=[plan_id_state, domain_state])

        with gr.Tab("Copilot"):
            gr.Markdown(
                "Ask about the most recently solved plan from any tab - e.g. "
                "\"why does SKU-002 need reordering?\" or \"what if we close WH-1?\""
            )
            with gr.Row():
                copilot_plan_id = gr.Textbox(label="Plan ID")
                copilot_domain = gr.Dropdown(choices=["replenishment", "routing", "network"], value="replenishment", label="Domain")
            copilot_question = gr.Textbox(label="Question", placeholder="why did you recommend this?")
            copilot_btn = gr.Button("Ask", variant="primary")
            copilot_output = gr.Markdown()
            copilot_btn.click(fn=ask_copilot, inputs=[copilot_question, copilot_plan_id, copilot_domain], outputs=copilot_output)

            plan_id_state.change(fn=lambda pid: pid, inputs=plan_id_state, outputs=copilot_plan_id)
            domain_state.change(fn=lambda d: d, inputs=domain_state, outputs=copilot_domain)

    return demo


if __name__ == "__main__":
    ui = build_ui()
    ui.launch(server_name="0.0.0.0", server_port=7860)
