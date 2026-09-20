"""Pure TypeSafe Choice request construction. No key access or HTTP code."""
from .digest import ACTIONS

INSTRUCTIONS = (
    "This is an OFFLINE RESEARCH comparison, not a claim of safe gameplay. "
    "Choose the offered movement with useful short-horizon separation from the tracked projectiles while preserving room to move, "
    "using the computed option descriptions. Unobserved hazards are unknown, not absent. "
    "Standing still is one action, not a safe default. Firing is independent of movement. "
    "Collision boxes and terrain are not established. Bounds apply only to the tested player/save, so do not infer collision safety."
)


def movement_request(digest, model="jev-latest"):
    return {"model": model,
            "state": {"experiment": "offline_projectile_family_action_comparison",
                      "projectile_locations": digest["tracked_locations"],
                      "coverage": "Six visually checked slots in one projectile family; not the complete scene",
                      "unknowns": digest["unknowns"], "assumptions": digest["forecast_assumptions"],
                      "firing": "independent; not selected by this question"},
            "questions": {"movement": {"type": "choice", "instructions": INSTRUCTIONS,
                "criteria": {action: digest["actions"][action]["description"] for action in ACTIONS}}}}
