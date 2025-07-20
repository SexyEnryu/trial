import asyncio
from database import db

async def sync_all_teams():
    users_collection = db.users
    cursor = users_collection.find({})
    updated_count = 0
    total_users = 0
    async for user in cursor:
        total_users += 1
        team = user.get('team', [])
        collection = user.get('pokemon', [])
        if not team or not collection:
            continue
        collection_by_uuid = {poke['uuid']: poke for poke in collection if 'uuid' in poke}
        updated_team = []
        changed = False
        for poke in team:
            uuid = poke.get('uuid')
            if uuid and uuid in collection_by_uuid:
                # Use the latest version from the collection
                updated_team.append(collection_by_uuid[uuid])
                if poke != collection_by_uuid[uuid]:
                    changed = True
            else:
                updated_team.append(poke)
        if changed:
            await users_collection.update_one({"user_id": user["user_id"]}, {"$set": {"team": updated_team}})
            updated_count += 1
    print(f"Sync complete. {updated_count} out of {total_users} users had their teams updated.")

if __name__ == "__main__":
    asyncio.run(sync_all_teams()) 