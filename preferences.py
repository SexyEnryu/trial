# preferences.py - MongoDB-based preferences system
from database import get_or_create_user, users_collection

async def get_user_preferences(user_id: int):
    """Get user preferences for sorting and display from MongoDB"""
    try:
        user = await users_collection.find_one({"user_id": user_id})
        if user and 'preferences' in user:
            return user['preferences']
        else:
            # Create default preferences if they don't exist
            default_preferences = {
                'sort_by': 'name',
                'sort_direction': 'ascending',
                'display_options': ['level'],
                'show_numbering': False,
                'random_mode': False,
                'min_level': 1,
                'min_legendary': 0,
                'max_legendary': 6
            }
            # Save default preferences to database
            await users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"preferences": default_preferences}},
                upsert=True
            )
            return default_preferences
    except Exception as e:
        print(f"Error getting user preferences: {e}")
        # Return default preferences if there's an error
        return {
            'sort_by': 'name',
            'sort_direction': 'ascending',
            'display_options': ['level'],
            'show_numbering': False,
            'random_mode': False,
            'min_level': 1,
            'min_legendary': 0,
            'max_legendary': 6
        }

async def update_user_preferences(user_id: int, **kwargs):
    """Update user preferences in MongoDB"""
    try:
        # Get current preferences
        current_preferences = await get_user_preferences(user_id)
        
        # Update with new values
        current_preferences.update(kwargs)
        
        # Save to database
        result = await users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"preferences": current_preferences}},
            upsert=True
        )
        
        if result.modified_count > 0 or result.upserted_id:
            print(f"Successfully updated preferences for user {user_id}")
            return current_preferences
        else:
            print(f"Failed to update preferences for user {user_id}")
            return current_preferences
            
    except Exception as e:
        print(f"Error updating user preferences: {e}")
        return await get_user_preferences(user_id)

def get_sort_display_name(sort_by):
    """Get display name for sort option"""
    sort_names = {
        'order_caught': 'Order caught',
        'pokedex_number': 'Pokedex number',
        'level': 'Level',
        'iv_points': 'IV points',
        'ev_points': 'EV points',
        'name': 'Name',
        'nature': 'Nature',
        'type': 'Type',
        'catch_rate': 'Catch rate',
        'hp_points': 'HP points',
        'attack_points': 'Attack points',
        'defense_points': 'Defense points',
        'sp_attack_points': 'Sp. Attack points',
        'sp_defense_points': 'Sp. Defense points',
        'speed_points': 'Speed points',
        'total_stats_points': 'Total stats points'
    }
    return sort_names.get(sort_by, 'Unknown')

def get_display_name(display_option):
    """Get display name for display option"""
    display_names = {
        'none': 'None',
        'level': 'Level',
        'iv_points': 'IV points',
        'ev_points': 'EV points',
        'nature': 'Nature',
        'type': 'Type',
        'type_symbol': 'Type symbol',
        'catch_rate': 'Catch rate',
        'hp_points': 'HP points',
        'attack_points': 'Attack points',
        'defense_points': 'Defense points',
        'sp_attack_points': 'Sp. Attack points',
        'sp_defense_points': 'Sp. Defense points',
        'speed_points': 'Speed points',
        'total_stats_points': 'Total stats points'
    }
    return display_names.get(display_option, 'Unknown')

async def check_starter_package(user_id: int, username: str = None, first_name: str = None):
    """Check if user has claimed their starter package"""
    user = await get_or_create_user(user_id, username, first_name)
    
    if not user:
        return False, "❌ User data not found! Please try again."
    
    if not user.get('already_started', False):
        return False, "❌ You need to claim your starter package first! Use /start command to begin your Pokémon journey."
    
    return True, user