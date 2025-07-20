import asyncio
import aiohttp
import json
import os

API_MOVES = "https://pokeapi.co/api/v2/move?limit=1000"

def get_machine_code(machine):
    name = machine.get("name")
    if name:
        return name
    # Fallback to URL parsing if name missing
    url = machine.get("url", "")
    parts = url.rstrip("/").split("/")
    num = parts[-1] if parts else ""
    return f"tm{num.zfill(2)}"

async def fetch_move(session, move_entry):
    async with session.get(move_entry["url"]) as resp:
        data = await resp.json()
    # Filter only damaging TM/HM moves
    if not data.get("machines") or not data.get("power"):
        return None
    results = []
    for m in data["machines"]:
        code = get_machine_code(m["machine"])
        # Only add once per machine
        results.append({
            "number": code,
            "move": data["name"],
            "power": data["power"],
            "accuracy": data["accuracy"],
        })
    return results

async def main():
    async with aiohttp.ClientSession() as s:
        moves = (await (await s.get(API_MOVES)).json())["results"]
        all_entries = []
        for entry in moves:
            res = await fetch_move(s, entry)
            if res:
                all_entries.extend(res)

    # Build JSON by TM/HM number, keeping latest if duplicates
    tmhm = {e["number"]: e for e in all_entries}

    with open("tm_hm_moves.json", "w") as f:
        json.dump(tmhm, f, indent=2)
    print(f"✅ Extracted {len(tmhm)} damaging TM/HM moves.")

if __name__ == "__main__":
    asyncio.run(main())
