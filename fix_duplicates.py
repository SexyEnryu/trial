#!/usr/bin/env python3
"""
Database Duplicate Cleanup Script
Removes duplicate mega stones, Z-crystals, and plates from all users
"""

import asyncio
import sys
import os
from collections import Counter

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import MONGO_URI
from motor.motor_asyncio import AsyncIOMotorClient

async def cleanup_duplicates():
    """Remove duplicate items from all users in the database"""
    
    # Connect to MongoDB
    client = AsyncIOMotorClient(MONGO_URI)
    db = client.pokemon_bot
    users_collection = db.users
    
    print("🔍 Starting duplicate cleanup...")
    
    # Get all users
    users = await users_collection.find({}).to_list(length=None)
    print(f"📊 Found {len(users)} users to check")
    
    total_fixes = 0
    users_fixed = 0
    
    for user in users:
        user_id = user.get('user_id')
        if not user_id:
            continue
            
        user_fixes = 0
        updates = {}
        
        # Check mega stones
        if 'mega_stones' in user and user['mega_stones']:
            original_count = len(user['mega_stones'])
            unique_stones = list(dict.fromkeys(user['mega_stones']))  # Preserve order, remove duplicates
            if len(unique_stones) != original_count:
                updates['mega_stones'] = unique_stones
                user_fixes += original_count - len(unique_stones)
                print(f"  User {user_id}: Removed {original_count - len(unique_stones)} duplicate mega stones")
        
        # Check Z-crystals
        if 'z_crystals' in user and user['z_crystals']:
            original_count = len(user['z_crystals'])
            unique_crystals = list(dict.fromkeys(user['z_crystals']))  # Preserve order, remove duplicates
            if len(unique_crystals) != original_count:
                updates['z_crystals'] = unique_crystals
                user_fixes += original_count - len(unique_crystals)
                print(f"  User {user_id}: Removed {original_count - len(unique_crystals)} duplicate Z-crystals")
        
        # Check plates
        if 'plates' in user and user['plates']:
            original_count = len(user['plates'])
            unique_plates = list(dict.fromkeys(user['plates']))  # Preserve order, remove duplicates
            if len(unique_plates) != original_count:
                updates['plates'] = unique_plates
                user_fixes += original_count - len(unique_plates)
                print(f"  User {user_id}: Removed {original_count - len(unique_plates)} duplicate plates")
        
        # Apply updates if any
        if updates:
            try:
                await users_collection.update_one(
                    {"user_id": user_id},
                    {"$set": updates}
                )
                total_fixes += user_fixes
                users_fixed += 1
            except Exception as e:
                print(f"  ❌ Error updating user {user_id}: {e}")
    
    print(f"\n✅ Cleanup completed!")
    print(f"📈 Users fixed: {users_fixed}")
    print(f"🗑️  Total duplicates removed: {total_fixes}")
    
    # Close database connection
    client.close()

async def show_duplicate_stats():
    """Show statistics about duplicates in the database"""
    
    # Connect to MongoDB
    client = AsyncIOMotorClient(MONGO_URI)
    db = client.pokemon_bot
    users_collection = db.users
    
    print("📊 Analyzing duplicate statistics...")
    
    # Get all users
    users = await users_collection.find({}).to_list(length=None)
    
    total_users = len(users)
    users_with_duplicates = 0
    total_duplicates = 0
    
    mega_stone_duplicates = 0
    z_crystal_duplicates = 0
    plate_duplicates = 0
    
    for user in users:
        user_has_duplicates = False
        
        # Check mega stones
        if 'mega_stones' in user and user['mega_stones']:
            original_count = len(user['mega_stones'])
            unique_count = len(set(user['mega_stones']))
            if original_count != unique_count:
                mega_stone_duplicates += original_count - unique_count
                user_has_duplicates = True
        
        # Check Z-crystals
        if 'z_crystals' in user and user['z_crystals']:
            original_count = len(user['z_crystals'])
            unique_count = len(set(user['z_crystals']))
            if original_count != unique_count:
                z_crystal_duplicates += original_count - unique_count
                user_has_duplicates = True
        
        # Check plates
        if 'plates' in user and user['plates']:
            original_count = len(user['plates'])
            unique_count = len(set(user['plates']))
            if original_count != unique_count:
                plate_duplicates += original_count - unique_count
                user_has_duplicates = True
        
        if user_has_duplicates:
            users_with_duplicates += 1
    
    total_duplicates = mega_stone_duplicates + z_crystal_duplicates + plate_duplicates
    
    print(f"\n📈 Duplicate Statistics:")
    print(f"   Total users: {total_users}")
    print(f"   Users with duplicates: {users_with_duplicates}")
    print(f"   Total duplicates: {total_duplicates}")
    print(f"   Mega stone duplicates: {mega_stone_duplicates}")
    print(f"   Z-crystal duplicates: {z_crystal_duplicates}")
    print(f"   Plate duplicates: {plate_duplicates}")
    
    # Close database connection
    client.close()

async def main():
    """Main function"""
    if len(sys.argv) > 1 and sys.argv[1] == "--stats":
        await show_duplicate_stats()
    else:
        print("🧹 Database Duplicate Cleanup Tool")
        print("This will remove duplicate mega stones, Z-crystals, and plates from all users.")
        
        response = input("\nDo you want to proceed? (y/N): ").strip().lower()
        if response in ['y', 'yes']:
            await cleanup_duplicates()
        else:
            print("❌ Cleanup cancelled.")

if __name__ == "__main__":
    asyncio.run(main()) 