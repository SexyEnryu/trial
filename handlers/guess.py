import asyncio
import random
import secrets
import json
import os
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.types import BufferedInputFile
import aiohttp
from io import BytesIO

# Import your custom modules (removed IdName import)
from database import update_user_balance

# Load text configurations
try:
    with open('./assets/variableJsons/texts.json', encoding='utf-8') as f:
        text = json.load(f)
except FileNotFoundError:
    # Fallback text if file doesn't exist
    text = {
        "english": {
            "InGuessMode": {"text": "A guess is already active in this chat! Please wait for it to finish."},
            "guessStart": {"text": "🎮<b>Who's that Pokémon?</b>"},
            "guessFailed": {"text": "<b>Time's up!</b>\n\nThe Pokémon was: <b>$poke_name</b>"},
            "guessDone": {"text": "🎉 <b>Congratulations $first_name!</b>\n\nYou guessed it right! It was <b>$poke_name</b>\n\n💵  +20 PokéDollars earned!"}
        }
    }

# Get image channel from environment
imageChannel = os.getenv("GUESS_IMAGES")

# Store active guess sessions
active_guesses = {}

# Simple user concurrency tracking (replacing middleware)
active_users = set()

def load_pokemon_data():
    """Load Pokemon data from poke.json (cached)"""
    from config import get_pokemon_data
    pokemon_data = get_pokemon_data()
    # Convert dict to list if needed for compatibility
    if isinstance(pokemon_data, dict):
        pokemon_list = list(pokemon_data.values()) if pokemon_data else []
        print(f"Successfully loaded cached Pokemon data")
        print(f"Loaded {len(pokemon_list)} Pokemon")
        return pokemon_list
    return pokemon_data if pokemon_data else []

# Load Pokemon data once
POKEMON_DATA = load_pokemon_data()

def get_pokemon_name_by_id(pokemon_id):
    """Get Pokemon name by ID from loaded data"""
    if POKEMON_DATA:
        pokemon = next((p for p in POKEMON_DATA if p["id"] == pokemon_id), None)
        if pokemon:
            return pokemon["name"].title()  # Capitalize first letter
    
    # Fallback - return a generic name if Pokemon not found
    return f"Pokemon #{pokemon_id}"

def get_random_pokemon():
    """Get a random Pokemon from the loaded data"""
    if POKEMON_DATA:
        return random.choice(POKEMON_DATA)
    else:
        # Fallback to random ID if no data loaded
        pokemon_id = random.randint(1, 1026)
        return {
            "id": pokemon_id,
            "name": f"Pokemon #{pokemon_id}"
        }

async def download_image(url: str) -> BytesIO:
    """Download image from URL and return as BytesIO"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    image_data = await response.read()
                    return BytesIO(image_data)
    except Exception as e:
        print(f"Error downloading image: {e}")
    return None

def add_user_concurrency(user_id):
    """Simple concurrency check (replacing middleware)"""
    if user_id in active_users:
        return False
    active_users.add(user_id)
    return True

def remove_user_concurrency(user_id):
    """Remove user from active users"""
    active_users.discard(user_id)

def set_guess_pokemon(chat_id, guess_code):
    """Set up a new Pokemon guess session"""
    # Get random Pokemon from loaded data
    pokemon = get_random_pokemon()
    pokemon_id = pokemon["id"]
    pokemon_name = pokemon["name"].title()  # Ensure proper capitalization
    
    # Generate image URL
    if imageChannel:
        image_url = imageChannel + str(pokemon_id)
    else:
        # Try using the GitHub repository for Pokemon images
        image_url = f"https://raw.githubusercontent.com/OfficialCodinary/pokeImages/main/{str(pokemon_id).zfill(3)}.png"
    
    active_guesses[chat_id] = {
        "name": pokemon_name,
        "guess_code": guess_code,
        "pokemon_id": pokemon_id,
        "start_time": asyncio.get_event_loop().time()
    }
    
    print(f"Set guess Pokemon: ID={pokemon_id}, Name={pokemon_name}")
    return image_url

def get_guess_pokemon_name(chat_id):
    """Get the Pokemon name for active guess"""
    return active_guesses.get(chat_id, {}).get('name')

def delete_guess(chat_id):
    """Remove active guess session"""
    active_guesses.pop(chat_id, None)

def is_guessing(chat_id, guess_code):
    """Check if there's an active guess with matching code"""
    if chat_id in active_guesses:
        entry = active_guesses.get(chat_id)
        return entry.get("guess_code") == guess_code
    return False

def is_in_guess(chat_id):
    """Check if chat has active guess session"""
    return chat_id in active_guesses

async def guess_timeout(chat_id: int, original_message: Message, guess_code: str):
    """Handle guess timeout"""
    try:
        await asyncio.sleep(30)  # Wait 30 seconds
        
        if is_guessing(chat_id, guess_code):
            pokemon_name = get_guess_pokemon_name(chat_id)
            delete_guess(chat_id)
            
            language = "english"
            fail_text = text[language]['guessFailed']['text']
            msg = fail_text.replace("$poke_name", pokemon_name)
            
            await original_message.reply(text=msg, parse_mode='HTML')
    except Exception as e:
        print(f"Error in guess timeout: {e}")

# Create router
guess_router = Router()

@guess_router.message(Command("guess"))
async def start_guess(message: Message):
    """Start a Pokemon guessing game"""
    user_id = message.from_user.id
    
    # Simple concurrency check
    if not add_user_concurrency(user_id):
        await message.reply("Please wait, you have another command running!")
        return
    
    try:
        # Only allow in groups/supergroups
        if message.chat.type not in ["group", "supergroup"]:
            await message.reply("This command only works in groups!")
            return
        
        # Check if Pokemon data is loaded
        if not POKEMON_DATA:
            await message.reply("❌ Pokemon data not loaded! Please check if poke.json exists.")
            return
        
        language = "english"
        chat_id = message.chat.id
        
        # Check if there's already an active guess
        if is_in_guess(chat_id):
            await message.reply(text=text[language]['InGuessMode']['text'])
            return
        
        # Generate unique guess code
        guess_code = secrets.token_hex(8)
        
        # Set up Pokemon guess
        image_url = set_guess_pokemon(chat_id, guess_code)
        pokemon_name = get_guess_pokemon_name(chat_id)
        
        print(f"Pokemon selected: {pokemon_name}")
        
        # Try to send image
        if image_url:
            try:
                # Try downloading image first
                image_data = await download_image(image_url)
                if image_data:
                    await message.reply_photo(
                        photo=BufferedInputFile(image_data.getvalue(), filename=f"pokemon_guess.png"),
                        caption=text[language]['guessStart']['text'],
                        parse_mode='HTML'
                    )
                else:
                    # If download fails, try direct URL
                    await message.reply_photo(
                        photo=image_url,
                        caption=text[language]['guessStart']['text'],
                        parse_mode='HTML'
                    )
            except Exception as e:
                print(f"Error sending image: {e}")
                # Send text-only message if image fails
                await message.reply(
                    text=text[language]['guessStart']['text'] + "\n(Image unavailable)",
                    parse_mode='HTML'
                )
        else:
            # No image URL available
            await message.reply(
                text=text[language]['guessStart']['text'] + "\n(Image unavailable)",
                parse_mode='HTML'
            )
        
        # Start timeout task
        asyncio.create_task(guess_timeout(chat_id, message, guess_code))
        
    except Exception as e:
        print(f"Error in start_guess: {e}")
        await message.reply("An error occurred while starting the guess!")
    finally:
        # Always remove user from active users
        remove_user_concurrency(user_id)

@guess_router.message(F.text)
async def check_guess(message: Message):
    """Check if message is a correct Pokemon guess"""
    chat_id = message.chat.id
    
    # Only process if there's an active guess
    if not is_in_guess(chat_id):
        return
    
    try:
        language = "english"
        correct_name = get_guess_pokemon_name(chat_id)
        
        if not correct_name:
            return
        
        user_guess = message.text.strip().lower()
        
        # Check if the guess is correct (case-insensitive)
        if user_guess == correct_name.lower():
            # Remove active guess
            delete_guess(chat_id)
            
            # Update user balance
            try:
                await update_user_balance(message.from_user.id, 20)
            except Exception as e:
                print(f"Error updating balance: {e}")
            
            # Send success message
            raw_text = text[language]['guessDone']['text']
            poke_added_text = raw_text.replace("$poke_name", correct_name)
            msg = poke_added_text.replace("$first_name", message.from_user.first_name)
            
            await message.reply(text=msg, parse_mode='HTML')
            
    except Exception as e:
        print(f"Error in check_guess: {e}")

# Export the router
router = guess_router