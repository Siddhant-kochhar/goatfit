#!/usr/bin/env python3
"""
Simple script to clear MongoDB collections for testing
"""
import pymongo
import os
from dotenv import load_dotenv

load_dotenv()

# MongoDB Configuration
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "hadesfit")

def clear_database():
    try:
        # Connect to MongoDB
        client = pymongo.MongoClient(MONGODB_URL)
        db = client[DATABASE_NAME]
        
        # Clear all collections
        users_result = db.users.delete_many({})
        contacts_result = db.emergency_contacts.delete_many({})
        alerts_result = db.health_alerts.delete_many({})
        
        print(f"🗄️ Database cleared:")
        print(f"   Users deleted: {users_result.deleted_count}")
        print(f"   Emergency contacts deleted: {contacts_result.deleted_count}")
        print(f"   Health alerts deleted: {alerts_result.deleted_count}")
        print("✅ Database is now clean for testing")
        
        client.close()
        
    except Exception as e:
        print(f"❌ Error clearing database: {e}")

if __name__ == "__main__":
    clear_database()
