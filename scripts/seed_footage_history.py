"""Seed a small one-time blocklist of scene assets that were duplicated in two posts.

This file is intentionally limited to public asset identifiers and metadata. The full
30-day footage history is persisted between Actions runs with the workflow cache.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

STATE = Path(__file__).resolve().parents[1] / ".pipeline" / "state"
HISTORY = STATE / "footage_history.json"

# These assets were observed in both the 20 Nov 2026 Astro Tobby videos.
# Their recent-use timestamps stop the same visual set from appearing again.
KNOWN_DUPLICATES = [
    ("openverse:274e38b4-914d-4b51-9789-e463758bfaa6", "The Making of Harry Potter 29-05-2012", "Openverse"),
    ("openverse:45fd5ea0-3ef7-4ec8-aacb-e3d2452f895c", "Small Bedroom Recording Studio", "Openverse"),
    ("openverse:cf11d991-80be-4cb6-bc97-89381b933c3f", "Computer landscape", "Openverse"),
    ("openverse:af73b8ea-3ef7-4df5-8cc8-621bbbf13034", "I am Typing", "Openverse"),
    ("openverse:9c842c2a-77e4-4738-93e1-6db63cc852d0", "Lake Woodruff Volusia 5 Prescribed Fire Febuary 2014", "Openverse"),
    ("openverse:e7380edf-237e-4a94-9e7b-02add930d7e3", "Green Day Concert Crowd - Put Your Hands Up For Green Day", "Openverse"),
    ("openverse:c5c6614b-64c5-41a8-83dc-5be1681a4fb0", "IKEA Bed", "Openverse"),
    ("openverse:9197b7a6-bb51-4dba-bd9c-83577d7f1e8a", "jarre . in>doors . helsinki", "Openverse"),
    ("openverse:98d353c0-3197-499d-b517-de6d1ff83b20", "R.U.R. (Rossum's Universal Robots)", "Openverse"),
    ("openverse:f6f398f9-2f84-423b-9313-bd4ae5291d51", "Garage Startup Philosophy", "Openverse"),
    ("wikimedia-commons:46623049", "A-Quick-Guide-to-Software-Licensing-for-the-Scientist-Programmer-pcbi.1002598.g002.jpg", "Wikimedia Commons"),
    ("openverse:ad01829f-99fc-43bc-acb4-3905cc00cb42", "Tanzania Pandemic Disaster Response Exercise, March 2011", "Openverse"),
    ("openverse:d0046237-f569-47ee-a812-fa9b0d140e73", "Freedom Center Library, Knott's Berry Farm", "Openverse"),
    ("openverse:3a138927-0f17-41fe-a1b9-090059521095", "Business freelance Asian woman working, doing projects and sending email on laptop or computer while sitting on table in cafe. Lifestyle smart beautiful women working at coffee shop concepts.", "Openverse"),
    ("openverse:c14f07ea-7c44-4036-884d-07bc5ea57283", "Electronic Circuit Board Close Up", "Openverse"),
    ("openverse:3ca450ea-3819-4ca5-b4b8-7ad26a0347fe", "Storms over Streeterville (12)", "Openverse"),
    ("openverse:0921a000-950b-4f0b-bc4c-e9e86b990917", "People working on a laptop in a meeting", "Openverse"),
    ("openverse:baec530b-71cc-42ce-af52-c8aae3a8979f", "Small Bedroom Recording Studio", "Openverse"),
    ("openverse:db36ff42-8e04-4a54-8cfb-d980645b541b", "Green Day Concert Stage (Montreal) - Green Day is Ever Green", "Openverse"),
    ("openverse:9f34ba0e-821f-4e2e-917a-7aa9a8fd0382", "showtime ( #cc )", "Openverse"),
    ("openverse:22531886-1a54-4dc9-b760-bd232f38122b", "Small Bedroom Studio", "Openverse"),
]


def main() -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    try:
        raw = json.loads(HISTORY.read_text(encoding="utf-8"))
        items = raw.get("items", []) if isinstance(raw, dict) else []
    except (OSError, ValueError, json.JSONDecodeError):
        items = []

    known = {item.get("id") for item in items if isinstance(item, dict)}
    now = time.time()
    added = 0
    for asset_id, title, provider in KNOWN_DUPLICATES:
        if asset_id not in known:
            items.append({
                "id": asset_id,
                "title": title,
                "provider": provider,
                "used_at": now,
                "reason": "seeded_duplicate_asset_guard",
            })
            known.add(asset_id)
            added += 1

    items.sort(key=lambda item: float(item.get("used_at", 0)), reverse=True)
    HISTORY.write_text(
        json.dumps({"items": items[:100000]}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Visual duplicate guard ready: {added} seeded, {len(items[:100000])} recent asset IDs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
