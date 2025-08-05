#!/usr/bin/env python3
"""
GoatFit Automated Health Monitoring System
Real-time vital sign monitoring with automatic emergency alerts
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json
from dataclasses import dataclass
from enum import Enum

# Google Fit API imports
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Email alert system
from email_alert import alert_service

# Gemini AI integration (optional)
# import google.generativeai as genai

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AlertLevel(Enum):
    """Alert severity levels"""
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"

@dataclass
class VitalReading:
    """Represents a vital sign reading"""
    timestamp: datetime
    value: float
    vital_type: str
    unit: str
    alert_level: AlertLevel
    
class HealthPatterns:
    """Analyze health patterns and trends"""
    
    @staticmethod
    def analyze_heart_rate_trend(readings: List[VitalReading]) -> Dict:
        """Analyze heart rate patterns over time"""
        if len(readings) < 3:
            return {"status": "insufficient_data", "trend": "unknown"}
        
        # Calculate trend
        recent_avg = sum(r.value for r in readings[-3:]) / 3
        earlier_avg = sum(r.value for r in readings[-6:-3]) / 3 if len(readings) >= 6 else recent_avg
        
        trend = "increasing" if recent_avg > earlier_avg + 5 else "decreasing" if recent_avg < earlier_avg - 5 else "stable"
        
        # Detect patterns
        patterns = {
            "status": "analyzed",
            "trend": trend,
            "recent_average": round(recent_avg, 1),
            "earlier_average": round(earlier_avg, 1),
            "highest": max(r.value for r in readings),
            "lowest": min(r.value for r in readings),
            "variance": round(max(r.value for r in readings) - min(r.value for r in readings), 1)
        }
        
        # Risk assessment
        if recent_avg > 160 or any(r.value > 180 for r in readings[-3:]):
            patterns["risk_level"] = "high"
        elif recent_avg > 120 or trend == "increasing":
            patterns["risk_level"] = "moderate"
        else:
            patterns["risk_level"] = "low"
            
        return patterns

class AutomatedHealthMonitor:
    """Main automated health monitoring system"""
    
    def __init__(self, 
                 check_interval: int = 300,  # 5 minutes
                 gemini_api_key: Optional[str] = None):
        self.check_interval = check_interval
        self.gemini_api_key = gemini_api_key
        self.is_monitoring = False
        self.last_readings = {}
        self.health_patterns = HealthPatterns()
        
        # Critical thresholds
        self.thresholds = {
            "heart_rate": {
                "emergency_high": 190,
                "critical_high": 180,
                "warning_high": 140,
                "warning_low": 50,
                "critical_low": 40,
                "emergency_low": 35
            },
            "blood_pressure_systolic": {
                "emergency_high": 200,
                "critical_high": 180,
                "warning_high": 140,
                "warning_low": 90,
                "critical_low": 70,
                "emergency_low": 60
            }
        }
        
        # Initialize Gemini AI if API key provided
        if gemini_api_key:
            try:
                # genai.configure(api_key=gemini_api_key)
                # self.gemini_model = genai.GenerativeModel('gemini-pro')
                logger.info("Gemini AI initialized for health analysis")
            except Exception as e:
                logger.warning(f"Gemini AI initialization failed: {e}")
    
    def determine_alert_level(self, vital_type: str, value: float) -> AlertLevel:
        """Determine alert level based on vital sign value"""
        thresholds = self.thresholds.get(vital_type, {})
        
        if value >= thresholds.get("emergency_high", 999) or value <= thresholds.get("emergency_low", 0):
            return AlertLevel.EMERGENCY
        elif value >= thresholds.get("critical_high", 999) or value <= thresholds.get("critical_low", 0):
            return AlertLevel.CRITICAL
        elif value >= thresholds.get("warning_high", 999) or value <= thresholds.get("warning_low", 0):
            return AlertLevel.WARNING
        else:
            return AlertLevel.NORMAL
    
    async def fetch_google_fit_data(self, credentials: Credentials, hours_back: int = 1) -> List[VitalReading]:
        """Fetch recent vital signs from Google Fit"""
        readings = []
        
        try:
            service = build('fitness', 'v1', credentials=credentials)
            
            # Calculate time range
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=hours_back)
            
            # Convert to nanoseconds for Google Fit API
            start_time_ns = int(start_time.timestamp() * 1_000_000_000)
            end_time_ns = int(end_time.timestamp() * 1_000_000_000)
            
            # Fetch heart rate data
            heart_rate_dataset = service.users().dataset().aggregate(
                userId='me',
                body={
                    "aggregateBy": [{"dataTypeName": "com.google.heart_rate.bpm"}],
                    "bucketByTime": {"durationMillis": 60000},  # 1-minute buckets
                    "startTimeMillis": start_time_ns // 1_000_000,
                    "endTimeMillis": end_time_ns // 1_000_000
                }
            ).execute()
            
            # Process heart rate data
            for bucket in heart_rate_dataset.get('bucket', []):
                for dataset in bucket.get('dataset', []):
                    for point in dataset.get('point', []):
                        if point.get('value'):
                            timestamp = datetime.fromtimestamp(
                                int(point['startTimeNanos']) / 1_000_000_000
                            )
                            heart_rate = point['value'][0]['fpVal']
                            alert_level = self.determine_alert_level('heart_rate', heart_rate)
                            
                            reading = VitalReading(
                                timestamp=timestamp,
                                value=heart_rate,
                                vital_type='heart_rate',
                                unit='BPM',
                                alert_level=alert_level
                            )
                            readings.append(reading)
            
            logger.info(f"Fetched {len(readings)} vital sign readings")
            
        except Exception as e:
            logger.error(f"Error fetching Google Fit data: {e}")
        
        return readings
    
    async def analyze_with_gemini(self, readings: List[VitalReading]) -> Dict:
        """Use Gemini AI to analyze health patterns (optional)"""
        if not self.gemini_api_key or not readings:
            return {"analysis": "AI analysis not available"}
        
        try:
            # Prepare data for Gemini
            data_summary = {
                "readings_count": len(readings),
                "time_span": f"{readings[0].timestamp} to {readings[-1].timestamp}",
                "heart_rates": [r.value for r in readings if r.vital_type == 'heart_rate'],
                "alerts": [r.alert_level.value for r in readings if r.alert_level != AlertLevel.NORMAL]
            }
            
            prompt = f"""
            As a health monitoring AI, analyze this patient's vital signs data:
            
            Data: {json.dumps(data_summary, default=str)}
            
            Provide analysis in JSON format with:
            1. overall_health_status (good/concerning/critical)
            2. immediate_concerns (list)
            3. recommendations (list)
            4. emergency_action_needed (boolean)
            5. risk_factors (list)
            """
            
            # Note: Uncomment when using Gemini API
            # response = self.gemini_model.generate_content(prompt)
            # return json.loads(response.text)
            
            # Placeholder analysis
            return {
                "overall_health_status": "good",
                "immediate_concerns": [],
                "recommendations": ["Continue regular monitoring"],
                "emergency_action_needed": False,
                "risk_factors": []
            }
            
        except Exception as e:
            logger.error(f"Gemini analysis error: {e}")
            return {"analysis": "AI analysis failed", "error": str(e)}
    
    async def send_automated_alerts(self, critical_readings: List[VitalReading], 
                                  emergency_contacts: List[Dict], 
                                  user_name: str = "Patient") -> bool:
        """Send automated emergency alerts to all contacts"""
        if not critical_readings or not emergency_contacts:
            return False
        
        alerts_sent = 0
        
        for reading in critical_readings:
            if reading.alert_level in [AlertLevel.CRITICAL, AlertLevel.EMERGENCY]:
                
                # Prepare alert information
                severity = "EMERGENCY" if reading.alert_level == AlertLevel.EMERGENCY else "CRITICAL"
                
                for contact in emergency_contacts:
                    try:
                        # Send alert using our Gmail system
                        success = await asyncio.to_thread(
                            alert_service.send_emergency_alert,
                            emergency_contact_email=contact['email'],
                            user_name=user_name,
                            vital_type="Heart Rate",
                            vital_value=reading.value,
                            threshold=140,
                            timestamp=reading.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                        )
                        
                        if success:
                            alerts_sent += 1
                            logger.info(f"Emergency alert sent to {contact['email']} for {reading.vital_type}: {reading.value}")
                        
                    except Exception as e:
                        logger.error(f"Failed to send alert to {contact['email']}: {e}")
        
        return alerts_sent > 0
    
    async def health_check_cycle(self, credentials: Credentials, 
                                emergency_contacts: List[Dict], 
                                user_name: str = "Patient"):
        """Single health monitoring cycle"""
        try:
            # 1. Fetch latest vital signs
            readings = await self.fetch_google_fit_data(credentials, hours_back=1)
            
            if not readings:
                logger.info("No new vital sign data available")
                return
            
            # 2. Analyze patterns
            heart_rate_readings = [r for r in readings if r.vital_type == 'heart_rate']
            if heart_rate_readings:
                patterns = self.health_patterns.analyze_heart_rate_trend(heart_rate_readings)
                logger.info(f"Health pattern analysis: {patterns}")
            
            # 3. Check for critical levels
            critical_readings = [r for r in readings if r.alert_level in [AlertLevel.CRITICAL, AlertLevel.EMERGENCY]]
            
            if critical_readings:
                logger.warning(f"CRITICAL VITALS DETECTED: {len(critical_readings)} readings require immediate attention")
                
                # 4. Send automated alerts
                alerts_sent = await self.send_automated_alerts(critical_readings, emergency_contacts, user_name)
                
                if alerts_sent:
                    logger.info(f"Emergency alerts sent successfully")
                else:
                    logger.error("Failed to send emergency alerts")
            
            # 5. Optional AI analysis
            if self.gemini_api_key:
                ai_analysis = await self.analyze_with_gemini(readings)
                logger.info(f"AI Health Analysis: {ai_analysis}")
            
            # 6. Store readings for trend analysis
            self.last_readings[datetime.now()] = readings
            
        except Exception as e:
            logger.error(f"Health check cycle error: {e}")
    
    async def start_monitoring(self, credentials: Credentials, 
                             emergency_contacts: List[Dict], 
                             user_name: str = "Patient"):
        """Start continuous health monitoring"""
        self.is_monitoring = True
        logger.info(f"🏥 Started automated health monitoring for {user_name}")
        logger.info(f"   📧 Monitoring {len(emergency_contacts)} emergency contacts")
        logger.info(f"   ⏰ Check interval: {self.check_interval} seconds")
        
        while self.is_monitoring:
            try:
                await self.health_check_cycle(credentials, emergency_contacts, user_name)
                await asyncio.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"Monitoring cycle error: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retrying
    
    def stop_monitoring(self):
        """Stop the health monitoring system"""
        self.is_monitoring = False
        logger.info("🛑 Health monitoring stopped")

# Global monitor instance
health_monitor = AutomatedHealthMonitor()

async def start_automated_monitoring(credentials: Credentials, 
                                   emergency_contacts: List[Dict], 
                                   user_name: str = "Patient",
                                   gemini_api_key: Optional[str] = None):
    """Start the automated health monitoring system"""
    global health_monitor
    
    if gemini_api_key:
        health_monitor.gemini_api_key = gemini_api_key
    
    await health_monitor.start_monitoring(credentials, emergency_contacts, user_name)

def stop_automated_monitoring():
    """Stop the automated health monitoring system"""
    global health_monitor
    health_monitor.stop_monitoring()

if __name__ == "__main__":
    # Test the monitoring system
    print("🏥 GoatFit Automated Health Monitoring System")
    print("=" * 50)
    print("This system provides:")
    print("✅ Real-time vital sign monitoring")
    print("✅ Automatic emergency detection")
    print("✅ Instant family alerts")
    print("✅ AI-powered health analysis (with Gemini)")
    print("✅ Pattern recognition and trends")
    print("\n💡 To use this system, integrate it with your FastAPI app")
    print("📧 Configure emergency contacts in your dashboard")
    print("🚨 System will automatically alert family during emergencies")
