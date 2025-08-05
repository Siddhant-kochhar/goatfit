"""
MongoDB Database Models and Connection for GoatFit Health Monitoring System
"""
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from bson import ObjectId
import asyncio
from dotenv import load_dotenv

load_dotenv()

# MongoDB Configuration
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "hadesfit")

# Global database connection
db_client: Optional[AsyncIOMotorClient] = None
db = None

async def connect_to_mongodb():
    """Connect to MongoDB database"""
    global db_client, db
    try:
        db_client = AsyncIOMotorClient(MONGODB_URL)
        db = db_client[DATABASE_NAME]
        
        # Test connection
        await db_client.admin.command('ping')
        print(f"🗄️ Connected to MongoDB: {DATABASE_NAME}")
        
        # Create indexes
        await create_indexes()
        
        return True
    except Exception as e:
        print(f"❌ Failed to connect to MongoDB: {e}")
        return False

async def close_mongodb_connection():
    """Close MongoDB connection"""
    global db_client
    if db_client:
        db_client.close()
        print("🗄️ MongoDB connection closed")

async def create_indexes():
    """Create database indexes for better performance"""
    try:
        # User email index (unique)
        await db.users.create_index("email", unique=True)
        
        # Google Fit user ID index
        await db.users.create_index("google_user_id")
        
        # Emergency contacts user reference index
        await db.emergency_contacts.create_index("user_id")
        
        # Health alerts timestamp index
        await db.health_alerts.create_index("timestamp")
        
        print("✅ Database indexes created successfully")
    except Exception as e:
        print(f"⚠️ Error creating indexes: {e}")

class UserModel:
    """User database model"""
    
    @staticmethod
    async def create_user(user_data: Dict[str, Any]) -> Optional[str]:
        """Create a new user"""
        try:
            user_doc = {
                "email": user_data["email"],
                "name": user_data["name"],
                "phone": user_data.get("phone", ""),
                "google_user_id": user_data.get("google_user_id", ""),
                "google_credentials": user_data.get("google_credentials", {}),
                "health_preferences": {
                    "high_hr_warning": user_data.get("high_hr_warning", 100),
                    "high_hr_critical": user_data.get("high_hr_critical", 120),
                    "low_hr_warning": user_data.get("low_hr_warning", 50),
                    "low_hr_critical": user_data.get("low_hr_critical", 40),
                    "notifications_enabled": True
                },
                "monitoring_enabled": True,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "last_health_check": None,
                "status": "active"
            }
            
            result = await db.users.insert_one(user_doc)
            print(f"✅ User created: {user_data['email']} (ID: {result.inserted_id})")
            return str(result.inserted_id)
            
        except Exception as e:
            print(f"❌ Error creating user: {e}")
            return None
    
    @staticmethod
    async def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
        """Get user by email"""
        try:
            user = await db.users.find_one({"email": email})
            if user:
                user["_id"] = str(user["_id"])
            return user
        except Exception as e:
            print(f"❌ Error getting user by email: {e}")
            return None
    
    @staticmethod
    async def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        try:
            user = await db.users.find_one({"_id": ObjectId(user_id)})
            if user:
                user["_id"] = str(user["_id"])
            return user
        except Exception as e:
            print(f"❌ Error getting user by ID: {e}")
            return None
    
    @staticmethod
    async def update_user(user_id: str, update_data: Dict[str, Any]) -> bool:
        """Update user information"""
        try:
            update_data["updated_at"] = datetime.now()
            result = await db.users.update_one(
                {"_id": ObjectId(user_id)}, 
                {"$set": update_data}
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"❌ Error updating user: {e}")
            return False
    
    @staticmethod
    async def get_all_monitored_users() -> List[Dict[str, Any]]:
        """Get all users who are enabled for monitoring"""
        try:
            cursor = db.users.find({"monitoring_enabled": True, "status": "active"})
            users = []
            async for user in cursor:
                user["_id"] = str(user["_id"])
                users.append(user)
            return users
        except Exception as e:
            print(f"❌ Error getting monitored users: {e}")
            return []
    
    @staticmethod
    async def get_all_users() -> List[Dict[str, Any]]:
        """Get all active users"""
        try:
            cursor = db.users.find({"status": "active"})
            users = []
            async for user in cursor:
                user["_id"] = str(user["_id"])
                users.append(user)
            return users
        except Exception as e:
            print(f"❌ Error getting all users: {e}")
            return []
        except Exception as e:
            print(f"❌ Error getting monitored users: {e}")
            return []

class EmergencyContactModel:
    """Emergency Contact database model"""
    
    @staticmethod
    async def add_contact(user_id: str, contact_data: Dict[str, Any]) -> Optional[str]:
        """Add emergency contact for a user"""
        try:
            contact_doc = {
                "user_id": user_id,
                "name": contact_data["name"],
                "email": contact_data["email"],
                "phone": contact_data.get("phone", ""),
                "relationship": contact_data["relationship"],
                "notifications_enabled": True,
                "created_at": datetime.now(),
                "updated_at": datetime.now()
            }
            
            result = await db.emergency_contacts.insert_one(contact_doc)
            print(f"✅ Emergency contact added for user {user_id}: {contact_data['name']}")
            return str(result.inserted_id)
            
        except Exception as e:
            print(f"❌ Error adding emergency contact: {e}")
            return None
    
    @staticmethod
    async def get_user_contacts(user_id: str) -> List[Dict[str, Any]]:
        """Get all emergency contacts for a user"""
        try:
            cursor = db.emergency_contacts.find({"user_id": user_id})
            contacts = []
            async for contact in cursor:
                contact["_id"] = str(contact["_id"])
                contacts.append(contact)
            return contacts
        except Exception as e:
            print(f"❌ Error getting user contacts: {e}")
            return []
    
    @staticmethod
    async def update_contact(contact_id: str, update_data: Dict[str, Any]) -> bool:
        """Update emergency contact"""
        try:
            update_data["updated_at"] = datetime.now()
            result = await db.emergency_contacts.update_one(
                {"_id": ObjectId(contact_id)}, 
                {"$set": update_data}
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"❌ Error updating contact: {e}")
            return False
    
    @staticmethod
    async def delete_contact(contact_id: str) -> bool:
        """Delete emergency contact"""
        try:
            result = await db.emergency_contacts.delete_one({"_id": ObjectId(contact_id)})
            return result.deleted_count > 0
        except Exception as e:
            print(f"❌ Error deleting contact: {e}")
            return False

class HealthAlertModel:
    """Health Alert database model"""
    
    @staticmethod
    async def create_alert(alert_data: Dict[str, Any]) -> Optional[str]:
        """Create a health alert record"""
        try:
            alert_doc = {
                "user_id": alert_data["user_id"],
                "alert_type": alert_data["alert_type"],  # "heart_rate", "blood_pressure", etc.
                "severity": alert_data["severity"],  # "WARNING", "CRITICAL"
                "value": alert_data["value"],
                "threshold": alert_data["threshold"],
                "message": alert_data["message"],
                "contacts_notified": alert_data.get("contacts_notified", []),
                "timestamp": datetime.now(),
                "status": "sent"
            }
            
            result = await db.health_alerts.insert_one(alert_doc)
            return str(result.inserted_id)
            
        except Exception as e:
            print(f"❌ Error creating health alert: {e}")
            return None
    
    @staticmethod
    async def get_user_alerts(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent alerts for a user"""
        try:
            cursor = db.health_alerts.find({"user_id": user_id}).sort("timestamp", -1).limit(limit)
            alerts = []
            async for alert in cursor:
                alert["_id"] = str(alert["_id"])
                alerts.append(alert)
            return alerts
        except Exception as e:
            print(f"❌ Error getting user alerts: {e}")
            return []

# Database connection functions for app startup/shutdown
async def init_database():
    """Initialize database connection"""
    success = await connect_to_mongodb()
    if success:
        print("🗄️ Database initialization complete")
    else:
        print("❌ Database initialization failed")
    return success

async def close_database():
    """Close database connection"""
    await close_mongodb_connection()
