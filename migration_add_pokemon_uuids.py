import asyncio
import uuid
from database import db, update_user_pokemon_collection

async def migrate_all_users_add_pokemon_uuids():
    users_collection = db.users
    users = users_collection.find({})
    updated_users = 0
    updated_pokemon = 0
    async for user in users:
        user_id = user['user_id']
        pokes = user.get('pokemon', [])
        changed = False
        for p in pokes:
            if 'uuid' not in p or not p['uuid']:
                p['uuid'] = str(uuid.uuid4())
                changed = True
                updated_pokemon += 1
        if changed:
            await update_user_pokemon_collection(user_id, pokes)
            updated_users += 1
    print(f"Migration complete. Updated {updated_users} users and {updated_pokemon} Pokémon with missing uuids.")

async def migrate_add_team_field():
    users_collection = db.users
    users = users_collection.find({})
    updated_users = 0
    async for user in users:
        if 'team' not in user:
            await users_collection.update_one(
                {"user_id": user['user_id']},
                {"$set": {"team": []}}
            )
            updated_users += 1
    print(f"Migration complete. Updated {updated_users} users with missing 'team' field.")

# To run both migrations in one go (optional):
async def run_all_migrations():
    await migrate_all_users_add_pokemon_uuids()
    await migrate_add_team_field()

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_all_migrations()) 