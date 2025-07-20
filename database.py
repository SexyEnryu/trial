import datetime
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI

# Optimized MongoDB client with connection pooling
clientx = AsyncIOMotorClient(
    MONGO_URI,
    maxPoolSize=50,  # Maximum number of connections in the pool
    minPoolSize=5,   # Minimum number of connections in the pool
    maxIdleTimeMS=30000,  # Close connections after 30 seconds of inactivity
    connectTimeoutMS=10000,  # 10 second connection timeout
    serverSelectionTimeoutMS=10000,  # 10 second server selection timeout
    retryWrites=True,
    compressors=['zlib'],  # Enable compression
)
db = clientx.pokemon_bot
users_collection = db.users

# --- Batch Database Operations Utilities ---

async def batch_pokemon_catch_operations(user_id: int, pokemon_data: dict, pokeball_name: str, reward_amount: int = 50):
    """
    Batch all database operations for a successful Pokemon catch.
    This includes updating pokeballs, adding pokemon, and updating balance concurrently.
    """
    try:
        # Get current user data first
        user = await users_collection.find_one({"user_id": user_id})
        if not user:
            return False, "User not found"
        
        # Update pokeball count
        updated_pokeballs = user.get('pokeballs', {}).copy()
        if updated_pokeballs.get(pokeball_name, 0) <= 0:
            return False, f"No {pokeball_name} balls available"
        
        updated_pokeballs[pokeball_name] -= 1
        
        # Execute all operations concurrently
        results = await asyncio.gather(
            update_user_pokeballs(user_id, updated_pokeballs),
            add_pokemon_to_user(user_id, pokemon_data),
            update_user_balance(user_id, reward_amount),
            return_exceptions=True
        )
        
        # Check if all operations succeeded
        for result in results:
            if isinstance(result, Exception):
                print(f"Error in batch pokemon catch operations: {result}")
                return False, str(result)
        
        return True, "All operations completed successfully"
        
    except Exception as e:
        print(f"Error in batch_pokemon_catch_operations: {e}")
        return False, str(e)

async def batch_user_validation_operations(user_id: int, username: str = "", first_name: str = ""):
    """
    Batch common user validation operations including user creation and data retrieval.
    Returns user data and common validation results.
    """
    try:
        # Get user and common collections concurrently
        user_task = asyncio.create_task(get_or_create_user(user_id, username, first_name))
        pokemon_collection_task = asyncio.create_task(get_user_pokemon_collection(user_id))
        
        user, pokemon_collection = await asyncio.gather(user_task, pokemon_collection_task)
        
        if not user:
            return False, "User data not found", None, None
        
        if not user.get('already_started', False):
            return False, "You need to claim your starter package first! Use /start command to begin your Pokémon journey.", None, None
        
        return True, user, pokemon_collection, None
        
    except Exception as e:
        print(f"Error in batch_user_validation_operations: {e}")
        return False, str(e), None, None

async def batch_reward_check_operations(user_id: int, reward_types: list[str] | None = None):
    """
    Batch check for multiple reward types (mega stones, z crystals, etc.).
    reward_types: list of reward types to check ['mega_stone', 'z_crystal']
    """
    try:
        if not reward_types:
            reward_types = ['mega_stone', 'z_crystal']
        
        tasks = []
        
        if 'mega_stone' in reward_types:
            tasks.append(('mega_stone', asyncio.create_task(get_user_mega_stones(user_id))))
        
        if 'z_crystal' in reward_types:
            tasks.append(('z_crystal', asyncio.create_task(get_user_z_crystals(user_id))))
        
        # Wait for all tasks to complete
        results = {}
        for reward_type, task in tasks:
            try:
                results[reward_type] = await task
            except Exception as e:
                print(f"Error getting {reward_type} for user {user_id}: {e}")
                results[reward_type] = []
        
        return True, results
        
    except Exception as e:
        print(f"Error in batch_reward_check_operations: {e}")
        return False, {}

async def batch_pokemon_encounter_operations(user_id: int, pokemon_id: int):
    """
    Batch common operations for pokemon encounters including checking if already caught.
    """
    try:
        # Check if pokemon already caught
        already_caught = await has_pokemon_been_caught(user_id, pokemon_id)
        
        return True, already_caught
        
    except Exception as e:
        print(f"Error in batch_pokemon_encounter_operations: {e}")
        return False, False

async def has_pokemon_been_caught(user_id: int, pokemon_id: int):
    """Check if user has already caught this Pokemon species"""
    try:
        user_pokemon = await get_user_pokemon_collection(user_id)
        for pokemon in user_pokemon:
            if pokemon.get('id') == pokemon_id:
                return True
        return False
    except Exception as e:
        print(f"Error checking if Pokemon was caught: {e}")
        return False

# --- End Batch Database Operations Utilities ---

async def get_or_create_user(user_id: int, username: str, first_name: str):
    """Get user from database or create new one"""
    user = await users_collection.find_one({"user_id": user_id})
    if user and 'pokerating' not in user:
        await users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"pokerating": 1000}}
        )
        user['pokerating'] = 1000
    """Get user from database or create new one"""
    # Ensure username and first_name are always str
    username = username or ""
    first_name = first_name or ""
    user = await users_collection.find_one({"user_id": user_id})
    
    if not user:
        # Create new user with starter pokeballs, currency, fishing rods, and default preferences
        new_user = {
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "pokedollars": 1000,
            "pokeballs": {
                "Regular": 10,
                "Great": 5,
                "Ultra": 3,
                "Repeat": 0,
                "Nest": 0,
                "Master": 0,
                "Dusk": 0,
                "Quick": 0,
                "Net": 0,
                "Level": 0,
                "Lure": 0,
                "Moon": 0,
                "Heavy": 0,
                "Fast": 0,
                "Sport": 0
            },
            "fishing_rods": {},  # Empty fishing rods collection for new users
            "berries": {},  # Empty berries collection for new users
            "vitamins": {},  # Empty vitamins collection for new users
            "inventory": {},  # Unified inventory for all items
            "pokemon": [],
            "team": [],  # Initialize team as empty list for new users
            "already_started": False,
            "current_region": "Kanto",  # Default region
            "preferences": {  # Default preferences
                "sort_by": "name",
                "sort_direction": "ascending",
                "display_options": ["level"],
                "show_numbering": False,
                "random_mode": False,
                "min_level": 1,
                "min_legendary": 0,
                "max_legendary": 6
            },
            "created_at": datetime.datetime.utcnow(),
            "last_active": datetime.datetime.utcnow(),
            "mega_stones": [],  # New: list of mega stones for user
            "z_crystals": [],  # New: list of z-crystals for user
            "plates": [],  # New: list of plates for user
            "has_mega_bracelet": False,  # New: mega bracelet status
            "has_z_ring": False,  # New: z-ring status
            "tms": {}  # New: TM collection for user
        }
        await users_collection.insert_one(new_user)
        return new_user
    else:
        # Update last active time
        await users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"last_active": datetime.datetime.utcnow()}}
        )
        
        # Add default preferences if they don't exist
        if 'preferences' not in user:
            default_preferences = {
                "sort_by": "name",
                "sort_direction": "ascending",
                "display_options": ["level"],
                "show_numbering": False,
                "random_mode": False,
                "min_level": 1,
                "min_legendary": 0,
                "max_legendary": 6
            }
            await users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"preferences": default_preferences}}
            )
            user['preferences'] = default_preferences
        
        # Add random_mode if it doesn't exist for existing users
        if 'random_mode' not in user.get('preferences', {}):
            await users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"preferences.random_mode": False}}
            )
            user['preferences']['random_mode'] = False
        
        # Add min_level if it doesn't exist for existing users
        if 'min_level' not in user.get('preferences', {}):
            await users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"preferences.min_level": 1}}
            )
            user['preferences']['min_level'] = 1
        
        # Add min_legendary if it doesn't exist for existing users
        if 'min_legendary' not in user.get('preferences', {}):
            await users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"preferences.min_legendary": 0}}
            )
            user['preferences']['min_legendary'] = 0
        
        # Add max_legendary if it doesn't exist for existing users
        if 'max_legendary' not in user.get('preferences', {}):
            await users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"preferences.max_legendary": 6}}
            )
            user['preferences']['max_legendary'] = 6
        
        # Add fishing_rods field if it doesn't exist for existing users
        if 'fishing_rods' not in user:
            await users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"fishing_rods": {}}}
            )
            user['fishing_rods'] = {}
        
        # Add berries field if it doesn't exist for existing users
        if 'berries' not in user:
            await users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"berries": {}}}
            )
            user['berries'] = {}
        
        # Add vitamins field if it doesn't exist for existing users
        if 'vitamins' not in user:
            await users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"vitamins": {}}}
            )
            user['vitamins'] = {}
        # Add inventory field if it doesn't exist for existing users
        if 'inventory' not in user:
            await users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"inventory": {}}}
            )
            user['inventory'] = {}
        # Add mega_stones field if it doesn't exist for existing users
        if 'mega_stones' not in user:
            await users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"mega_stones": []}}
            )
            user['mega_stones'] = []
        # Add z_crystals field if it doesn't exist for existing users
        if 'z_crystals' not in user:
            await users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"z_crystals": []}}
            )
            user['z_crystals'] = []
        
        # Add plates field if it doesn't exist for existing users
        if 'plates' not in user:
            await users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"plates": []}}
            )
            user['plates'] = []
        
        # Add tms field if it doesn't exist for existing users
        if 'tms' not in user:
            await users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"tms": {}}}
            )
            user['tms'] = {}
        
        # Add has_z_ring field if it doesn't exist for existing users
        if 'has_z_ring' not in user:
            await users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"has_z_ring": False}}
            )
            user['has_z_ring'] = False
            
        return user

async def mark_user_as_started(user_id: int):
    """Mark user as having started the adventure"""
    await users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"already_started": True}}
    )

async def get_user_region(user_id: int):
    """Get user's current region"""
    user = await users_collection.find_one({"user_id": user_id})
    return user.get("current_region", "Kanto") if user else "Kanto"

async def set_user_region(user_id: int, region: str):
    """Set user's current region"""
    await users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"current_region": region}}
    )

async def add_pokemon_to_user(user_id: int, pokemon_data: dict):
    """Add a caught Pokemon to user's collection"""
    try:
        # Ensure Pokemon has a UUID
        if not pokemon_data.get('uuid'):
            import uuid
            pokemon_data['uuid'] = str(uuid.uuid4())
        
        # Ensure Pokemon has required fields
        if not pokemon_data.get('name'):
            print(f"Pokemon data missing name field: {pokemon_data}")
            return False
        
        # Ensure user exists before adding Pokemon
        user = await db.users.find_one({"user_id": user_id})
        if not user:
            print(f"User {user_id} not found, cannot add Pokemon")
            return False
        
        # Check if this UUID already exists in the user's collection (prevent duplicates)
        existing_pokemon = user.get("pokemon", [])
        pokemon_uuid = pokemon_data.get('uuid')
        if any(p.get('uuid') == pokemon_uuid for p in existing_pokemon):
            print(f"Pokemon with UUID {pokemon_uuid} already exists for user {user_id}")
            return False
        
        # Add to user's pokemon array
        result = await db.users.update_one(
            {"user_id": user_id},
            {"$push": {"pokemon": pokemon_data}}
        )
        
        if result.modified_count > 0:
            print(f"Successfully added {pokemon_data['name']} (UUID: {pokemon_data.get('uuid')}) to user {user_id}")
            return True
        else:
            print(f"Failed to add Pokemon to user {user_id} - no documents modified")
            return False
            
    except Exception as e:
        print(f"Error adding Pokemon to user {user_id}: {e}")
        return False

async def update_user_pokeballs(user_id: int, pokeballs: dict):
    """Update user's pokeball inventory"""
    try:
        result = await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"pokeballs": pokeballs}}
        )
        
        if result.modified_count > 0:
            print(f"Successfully updated pokeballs for user {user_id}")
            return True
        else:
            print(f"Failed to update pokeballs for user {user_id}")
            return False
            
    except Exception as e:
        print(f"Error updating pokeballs for user {user_id}: {e}")
        return False

async def get_user_pokemon_collection(user_id: int):
    """Get user's Pokemon collection"""
    try:
        user = await db.users.find_one({"user_id": user_id})
        if user:
            return user.get("pokemon", [])
        return []
        
    except Exception as e:
        print(f"Error getting Pokemon collection for user {user_id}: {e}")
        return []

async def get_user_stats(user_id: int):
    """Get user's Pokemon statistics"""
    collection = await get_user_pokemon_collection(user_id)
    
    stats = {
        "total_caught": len(collection),
        "unique_species": len(set(p['id'] for p in collection)),
        "highest_level": max((p['level'] for p in collection), default=0),
        "legendary_count": sum(1 for p in collection if p['id'] in [144, 145, 146, 150, 151])
    }
    
    return stats

async def get_pokemon_by_id(user_id: int, pokemon_index: int):
    """Get a specific Pokemon from user's collection by index"""
    try:
        collection = await get_user_pokemon_collection(user_id)
        if 0 <= pokemon_index < len(collection):
            return collection[pokemon_index]
        return None
        
    except Exception as e:
        print(f"Error getting Pokemon by index for user {user_id}: {e}")
        return None

async def release_pokemon(user_id: int, pokemon_index: int):
    """Release a Pokemon from user's collection"""
    try:
        # Get the Pokemon first to show confirmation
        pokemon = await get_pokemon_by_id(user_id, pokemon_index)
        if not pokemon:
            return False, "Pokemon not found"
        
        # Remove from array using $unset and $pull
        result = await db.users.update_one(
            {"user_id": user_id},
            {"$unset": {f"pokemon.{pokemon_index}": 1}}
        )
        
        # Clean up null values
        await db.users.update_one(
            {"user_id": user_id},
            {"$pull": {"pokemon": None}}
        )
        
        if result.modified_count > 0:
            return True, f"Released {pokemon['name']} (Level {pokemon['level']})"
        else:
            return False, "Failed to release Pokemon"
            
    except Exception as e:
        print(f"Error releasing Pokemon for user {user_id}: {e}")
        return False, f"Error: {str(e)}"
    
async def get_user_pokemon(user_id: int) -> list:
    """Get all Pokemon for a user"""
    try:
        user = await db.users.find_one({"user_id": user_id})
        if user and 'pokemon' in user:
            return user['pokemon']
        return []
    except Exception as e:
        print(f"Error getting user pokemon: {e}")
        return []

async def update_pokemon_moves(user_id: int, pokemon_id: int, active_moves: list, pokemon_uuid: str | None = None) -> bool:
    """Update active moves for a specific Pokemon, matching by uuid if available, else by id."""
    try:
        # Find the user
        user = await db.users.find_one({"user_id": user_id})
        if not user or 'pokemon' not in user:
            return False
        # Find and update the specific Pokemon
        pokemon_list = user['pokemon']
        pokemon_found = False
        for i, pokemon in enumerate(pokemon_list):
            if pokemon_uuid and pokemon.get('uuid') == pokemon_uuid:
                pokemon_list[i]['active_moves'] = active_moves
                pokemon_found = True
                break
            elif not pokemon_uuid and pokemon.get('id') == pokemon_id:
                pokemon_list[i]['active_moves'] = active_moves
                pokemon_found = True
                break
        if not pokemon_found:
            return False
        # Update the user's Pokemon list
        result = await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"pokemon": pokemon_list}}
        )
        return result.modified_count > 0
    except Exception as e:
        print(f"Error updating pokemon moves: {e}")
        return False

async def update_pokemon_moveset(user_id: int, pokemon_id: int, moves: list, pokemon_uuid: str | None = None) -> bool:
    """Update moves list for a specific Pokemon, matching by uuid if available, else by id."""
    try:
        # Find the user
        user = await db.users.find_one({"user_id": user_id})
        if not user or 'pokemon' not in user:
            return False
        # Find and update the specific Pokemon
        pokemon_list = user['pokemon']
        pokemon_found = False
        for i, pokemon in enumerate(pokemon_list):
            if pokemon_uuid and pokemon.get('uuid') == pokemon_uuid:
                pokemon_list[i]['moves'] = moves
                pokemon_found = True
                break
            elif not pokemon_uuid and pokemon.get('id') == pokemon_id:
                pokemon_list[i]['moves'] = moves
                pokemon_found = True
                break
        if not pokemon_found:
            return False
        # Update the user's Pokemon list
        result = await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"pokemon": pokemon_list}}
        )
        return result.modified_count > 0
    except Exception as e:
        print(f"Error updating pokemon moveset: {e}")
        return False

async def get_pokemon_by_name(user_id: int, pokemon_name: str) -> list:
    """Get all Pokemon of a specific name for a user"""
    try:
        user_pokemon = await get_user_pokemon(user_id)
        matching_pokemon = []
        
        for pokemon in user_pokemon:
            if pokemon.get('name', '').lower() == pokemon_name.lower():
                matching_pokemon.append(pokemon)
        
        return matching_pokemon
    except Exception as e:
        print(f"Error getting pokemon by name: {e}")
        return []

async def update_user_balance(user_id: int, amount: int):
    """Update user's PokeDollars balance by adding the specified amount"""
    try:
        result = await db.users.update_one(
            {"user_id": user_id},
            {"$inc": {"pokedollars": amount}}
        )
        
        if result.modified_count > 0:
            print(f"Successfully updated balance for user {user_id}: +{amount} PokeDollars")
            return True
        else:
            print(f"Failed to update balance for user {user_id}")
            return False
            
    except Exception as e:
        print(f"Error updating balance for user {user_id}: {e}")
        return False

async def get_user_balance(user_id: int):
    """Get user's current PokeDollars balance"""
    try:
        user = await db.users.find_one({"user_id": user_id})
        if user:
            return user.get("pokedollars", 0)
        return 0
        
    except Exception as e:
        print(f"Error getting balance for user {user_id}: {e}")
        return 0

async def set_user_balance(user_id: int, amount: int):
    """Set user's PokeDollars balance to a specific amount"""
    try:
        result = await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"pokedollars": amount}}
        )
        
        if result.modified_count > 0:
            print(f"Successfully set balance for user {user_id}: {amount} PokeDollars")
            return True
        else:
            print(f"Failed to set balance for user {user_id}")
            return False
            
    except Exception as e:
        print(f"Error setting balance for user {user_id}: {e}")
        return False
    
async def update_user_fishing_rods(user_id: int, fishing_rods: dict):
    """Update user's fishing rod inventory"""
    try:
        result = await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"fishing_rods": fishing_rods}}
        )
        
        if result.modified_count > 0:
            print(f"Successfully updated fishing rods for user {user_id}")
            return True
        else:
            print(f"Failed to update fishing rods for user {user_id}")
            return False
            
    except Exception as e:
        print(f"Error updating fishing rods for user {user_id}: {e}")
        return False

async def get_user_fishing_rods(user_id: int):
    """Get user's fishing rod collection"""
    try:
        user = await db.users.find_one({"user_id": user_id})
        if user and isinstance(user.get("fishing_rods", {}), dict):
            return user.get("fishing_rods", {})
        return {}
    except Exception as e:
        print(f"Error getting fishing rods for user {user_id}: {e}")
        return {}

async def update_user_berries(user_id: int, berries: dict):
    """Update user's berry inventory"""
    try:
        result = await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"berries": berries}}
        )
        
        if result.modified_count > 0:
            print(f"Successfully updated berries for user {user_id}")
            return True
        else:
            print(f"Failed to update berries for user {user_id}")
            return False
            
    except Exception as e:
        print(f"Error updating berries for user {user_id}: {e}")
        return False

async def update_user_vitamins(user_id: int, vitamins: dict):
    """Update user's vitamin inventory"""
    try:
        result = await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"vitamins": vitamins}}
        )
        
        if result.modified_count > 0:
            print(f"Successfully updated vitamins for user {user_id}")
            return True
        else:
            print(f"Failed to update vitamins for user {user_id}")
            return False
            
    except Exception as e:
        print(f"Error updating vitamins for user {user_id}: {e}")
        return False

async def get_user_berries(user_id: int):
    """Get user's berry inventory"""
    try:
        user = await db.users.find_one({"user_id": user_id})
        if user and isinstance(user.get("berries", {}), dict):
            return user.get("berries", {})
        return {}
    except Exception as e:
        print(f"Error getting berries for user {user_id}: {e}")
        return {}

async def get_user_vitamins(user_id: int):
    """Get user's vitamin inventory"""
    try:
        user = await db.users.find_one({"user_id": user_id})
        if user and isinstance(user.get("vitamins", {}), dict):
            return user.get("vitamins", {})
        return {}
    except Exception as e:
        print(f"Error getting vitamins for user {user_id}: {e}")
        return {}

async def update_user_pokemon_collection(user_id: int, pokemon_collection: list):
    """Update user's entire Pokemon collection"""
    try:
        result = await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"pokemon": pokemon_collection}}
        )
        
        if result.modified_count > 0:
            print(f"Successfully updated Pokemon collection for user {user_id}")
            return True
        else:
            print(f"Failed to update Pokemon collection for user {user_id}")
            return False
            
    except Exception as e:
        print(f"Error updating Pokemon collection for user {user_id}: {e}")
        return False

# --- TEAM MANAGEMENT ---
async def get_user_team(user_id: int) -> list:
    """Return the user's current battle team (max 6 Pokémon).

    Falls back to the first six members of the full collection if the explicit
    `team` field has not been set yet.
    """
    try:
        user = await users_collection.find_one({"user_id": user_id})
        if not user:
            return []
        # Prefer explicit team list, else slice the collection.
        if "team" in user and isinstance(user["team"], list):
            return user["team"]
        return (user.get("pokemon_collection") or [])[:6]
    except Exception as e:
        print(f"Error get_user_team: {e}")
        return []

async def update_user_team(user_id: int, team: list) -> bool:
    """Persist the user's team list (up to 6 Pokémon)."""
    try:
        # Truncate to 6 for safety
        team = team[:6]
        await users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"team": team}},
            upsert=True,
        )
        return True
    except Exception as e:
        print(f"Error update_user_team: {e}")
        return False

# --- MEGA STONES ---
async def add_mega_stone_to_user(user_id: int, stone_name: str):
    """Add a mega stone to the user's inventory (by name, e.g. 'abomasite')"""
    try:
        result = await users_collection.update_one(
            {"user_id": user_id},
            {"$addToSet": {"mega_stones": stone_name}}
        )
        return result.modified_count > 0
    except Exception as e:
        print(f"Error adding mega stone to user {user_id}: {e}")
        return False

async def get_user_mega_stones(user_id: int):
    """Get a list of mega stones the user owns (list of stone names)"""
    try:
        user = await users_collection.find_one({"user_id": user_id})
        if user and 'mega_stones' in user:
            return user['mega_stones']
        return []
    except Exception as e:
        print(f"Error getting mega stones for user {user_id}: {e}")
        return []

# --- Z-CRYSTALS ---
async def add_z_crystal_to_user(user_id: int, crystal_name: str):
    """Add a z-crystal to the user's inventory (by name, e.g. 'firiumz')"""
    try:
        result = await users_collection.update_one(
            {"user_id": user_id},
            {"$addToSet": {"z_crystals": crystal_name}}
        )
        return result.modified_count > 0
    except Exception as e:
        print(f"Error adding z-crystal to user {user_id}: {e}")
        return False

async def get_user_z_crystals(user_id: int):
    """Get a list of z-crystals the user owns (list of crystal names)"""
    try:
        user = await users_collection.find_one({"user_id": user_id})
        if user and 'z_crystals' in user:
            return user['z_crystals']
        return []
    except Exception as e:
        print(f"Error getting z-crystals for user {user_id}: {e}")
        return []

# --- PLATES ---
async def add_plate_to_user(user_id: int, plate_name: str):
    """Add a plate to the user's inventory (by name, e.g. 'flame-plate')"""
    try:
        result = await users_collection.update_one(
            {"user_id": user_id},
            {"$addToSet": {"plates": plate_name}}
        )
        return result.modified_count > 0
    except Exception as e:
        print(f"Error adding plate to user {user_id}: {e}")
        return False

async def get_user_plates(user_id: int):
    """Get a list of plates the user owns (list of plate names)"""
    try:
        user = await users_collection.find_one({"user_id": user_id})
        if user and 'plates' in user:
            return user['plates']
        return []
    except Exception as e:
        print(f"Error getting plates for user {user_id}: {e}")
        return []

# --- Unified Inventory Functions ---
async def get_user_inventory(user_id: int) -> dict:
    """Get user's unified inventory (all items)"""
    try:
        user = await users_collection.find_one({"user_id": user_id})
        if user and isinstance(user.get("inventory", {}), dict):
            return user.get("inventory", {})
        return {}
    except Exception as e:
        print(f"Error getting inventory for user {user_id}: {e}")
        return {}

async def update_user_inventory(user_id: int, inventory: dict) -> bool:
    """Update user's unified inventory (all items)"""
    try:
        result = await users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"inventory": inventory}}
        )
        if result.modified_count > 0:
            print(f"Successfully updated inventory for user {user_id}")
            return True
        else:
            print(f"Failed to update inventory for user {user_id}")
            return False
    except Exception as e:
        print(f"Error updating inventory for user {user_id}: {e}")
        return False

async def set_user_mega_bracelet(user_id: int, value: bool):
    """Set user's mega bracelet status"""
    await users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"has_mega_bracelet": value}}
    )

async def set_user_z_ring(user_id: int, value: bool):
    """Set user's z-ring status"""
    await users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"has_z_ring": value}}
    )

async def get_user_tms(user_id: int) -> dict:
    """Get user's TM inventory"""
    try:
        user = await users_collection.find_one({"user_id": user_id})
        if not user:
            return {}
        
        # Ensure tms field exists
        if 'tms' not in user:
            await users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"tms": {}}}
            )
            return {}
        
        return user.get('tms', {})
    except Exception as e:
        print(f"Error getting user TMs: {e}")
        return {}

async def update_user_tms(user_id: int, tms: dict) -> bool:
    """Update user's TM inventory"""
    try:
        await users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"tms": tms}}
        )
        return True
    except Exception as e:
        print(f"Error updating user TMs: {e}")
        return False

async def remove_tm_from_user(user_id: int, tm_id: str, quantity: int = 1) -> bool:
    """Remove TM from user's inventory"""
    try:
        current_tms = await get_user_tms(user_id)
        
        if tm_id not in current_tms or current_tms[tm_id] < quantity:
            return False
        
        current_tms[tm_id] -= quantity
        
        # Remove TM completely if quantity becomes 0
        if current_tms[tm_id] <= 0:
            del current_tms[tm_id]
        
        return await update_user_tms(user_id, current_tms)
    except Exception as e:
        print(f"Error removing TM from user: {e}")
        return False

async def add_tm_to_user(user_id: int, tm_id: str, quantity: int = 1) -> bool:
    """Add TM to user's inventory"""
    try:
        current_tms = await get_user_tms(user_id)
        current_tms[tm_id] = current_tms.get(tm_id, 0) + quantity
        return await update_user_tms(user_id, current_tms)
    except Exception as e:
        print(f"Error adding TM to user: {e}")
        return False

async def get_user_pokerating(user_id: int):
    """Get user's PokeRating"""
    user = await users_collection.find_one({"user_id": user_id})
    return user.get('pokerating', 1000) if user else 1000

async def update_user_pokerating(user_id: int, amount: int):
    """Update user's PokeRating by adding the specified amount"""
    await users_collection.update_one(
        {"user_id": user_id},
        {"$inc": {"pokerating": amount}},
        upsert=True
    )

async def batch_tm_purchase_operations(user_id: int, tm_id: str, quantity: int, total_cost: int):
    """
    Batch all database operations for TM purchase.
    This includes updating balance and adding TM to inventory concurrently.
    """
    try:
        # Get current user data first
        user = await users_collection.find_one({"user_id": user_id})
        if not user:
            return False, "User not found"
        
        if user.get('pokedollars', 0) < total_cost:
            return False, "Insufficient PokeDollars"
        
        # Get current TM inventory
        current_tms = await get_user_tms(user_id)
        current_tms[tm_id] = current_tms.get(tm_id, 0) + quantity
        
        # Calculate new balance
        new_balance = user['pokedollars'] - total_cost
        
        # Execute all operations concurrently
        results = await asyncio.gather(
            set_user_balance(user_id, new_balance),
            update_user_tms(user_id, current_tms),
            return_exceptions=True
        )
        
        # Check if all operations succeeded
        for result in results:
            if isinstance(result, Exception):
                print(f"Error in batch TM purchase operations: {result}")
                return False, str(result)
        
        return True, "TM purchase completed successfully"
        
    except Exception as e:
        print(f"Error in batch_tm_purchase_operations: {e}")
        return False, str(e)

async def get_user_gym_progress(user_id: int) -> dict:
    """Get user's gym progress"""
    user = await users_collection.find_one({"user_id": user_id})
    return user.get('gym_progress', {}) if user else {}

async def update_user_gym_progress(user_id: int, region: str, defeated_leader_index: int):
    """Update user's gym progress for a specific region"""
    await users_collection.update_one(
        {"user_id": user_id},
        {"$set": {f"gym_progress.{region}": defeated_leader_index}}
    )

# === KILLED USER MANAGEMENT ===

async def kill_user(user_id: int) -> bool:
    """Mark a user as killed (disabled from using bot commands)"""
    try:
        result = await users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"is_killed": True, "killed_at": datetime.datetime.utcnow()}}
        )
        return result.modified_count > 0
    except Exception as e:
        print(f"Error killing user {user_id}: {e}")
        return False

async def unkill_user(user_id: int) -> bool:
    """Remove killed status from a user (re-enable bot commands)"""
    try:
        result = await users_collection.update_one(
            {"user_id": user_id},
            {"$unset": {"is_killed": "", "killed_at": ""}}
        )
        return result.modified_count > 0
    except Exception as e:
        print(f"Error unkilling user {user_id}: {e}")
        return False

async def is_user_killed(user_id: int) -> bool:
    """Check if a user is killed (disabled from using bot commands)"""
    try:
        user = await users_collection.find_one(
            {"user_id": user_id},
            {"is_killed": 1}
        )
        return user and user.get('is_killed', False)
    except Exception as e:
        print(f"Error checking if user {user_id} is killed: {e}")
        return False

async def get_killed_users() -> list:
    """Get list of all killed users"""
    try:
        cursor = users_collection.find(
            {"is_killed": True},
            {"user_id": 1, "first_name": 1, "username": 1, "killed_at": 1}
        ).sort("killed_at", -1)  # Sort by killed time, newest first
        
        killed_users = []
        async for user in cursor:
            killed_users.append({
                "user_id": user.get("user_id"),
                "first_name": user.get("first_name", "Unknown User"),
                "username": user.get("username"),
                "killed_at": user.get("killed_at")
            })
        
        return killed_users
    except Exception as e:
        print(f"Error getting killed users: {e}")
        return []

