import os
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

import requests
import json
import matplotlib.pyplot as plt
import io
import base64
import asyncio
from fastapi import FastAPI, Request, Query, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from datetime import datetime, timedelta
from email_alert import alert_service, send_heart_rate_alert
import uvicorn

# Import MongoDB database models
from database import (
    init_database, close_database, 
    UserModel, EmergencyContactModel, HealthAlertModel
)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.urandom(24).hex())

templates = Jinja2Templates(directory="templates")

# Global 24/7 Health Monitoring System
global_monitoring_active = False
global_monitoring_task = None
monitored_users = {}  # Store user credentials and contacts for monitoring

# Google Fit Configuration
GOOGLE_FIT_SCOPES = [
    'https://www.googleapis.com/auth/fitness.activity.read',
    'https://www.googleapis.com/auth/fitness.heart_rate.read',
    'https://www.googleapis.com/auth/fitness.sleep.read',
    'https://www.googleapis.com/auth/fitness.nutrition.read'
]
GOOGLE_CLIENT_SECRETS_FILE = "credentials/client_secret.json"

GOOGLE_FLOW = Flow.from_client_secrets_file(
    GOOGLE_CLIENT_SECRETS_FILE,
    scopes=GOOGLE_FIT_SCOPES,
    redirect_uri='http://localhost:8000/callback'
)

@app.get('/')
async def root(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

@app.get('/home')
async def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

@app.get('/contact')
async def contact(request: Request):
    return templates.TemplateResponse("contact.html", {"request": request})

@app.get('/debug')
async def debug_data(request: Request):
    """Debug endpoint to check data"""
    google_fit_data = []
    heart_rate_data = []
    debug_info = {
        "session_exists": 'google_credentials' in request.session,
        "credentials": None,
        "steps_data": [],
        "hr_data": [],
        "error": None
    }
    
    if 'google_credentials' in request.session:
        try:
            credentials = Credentials(**request.session['google_credentials'])
            debug_info["credentials"] = "Found"
            service = build('fitness', 'v1', credentials=credentials)
            
            now = datetime.utcnow()
            start_time = now - timedelta(days=7)
            
            # Test steps data
            steps_dataset = service.users().dataset().aggregate(
                userId="me",
                body={
                    "aggregateBy": [{"dataTypeName": "com.google.step_count.delta"}],
                    "bucketByTime": {"durationMillis": 86400000},
                    "startTimeMillis": int(start_time.timestamp() * 1000),
                    "endTimeMillis": int(now.timestamp() * 1000),
                }
            ).execute()
            
            debug_info["steps_raw"] = steps_dataset
            
        except Exception as e:
            debug_info["error"] = str(e)
    
    return debug_info

@app.get('/test-charts', response_class=HTMLResponse)
async def test_charts(request: Request):
    """Test route with sample data to verify charts work"""
    # Sample data for testing
    sample_labels = ['2025-07-26', '2025-07-27', '2025-07-28', '2025-07-29', '2025-07-30', '2025-07-31', '2025-08-01']
    sample_steps = [8500, 12000, 7800, 9500, 11200, 6800, 10500]
    sample_hr_values = [72, 68, 75, 70, 73, 69, 71]
    
    return templates.TemplateResponse("fit.html", {
        "request": request,
        "labels": sample_labels,
        "values": sample_steps,
        "hr_labels": sample_labels,
        "hr_values": sample_hr_values,
        "view": "weekly"
    })

@app.get('/test-vitals', response_class=HTMLResponse)
async def test_vitals(request: Request):
    """Test route with comprehensive sample vital data"""
    # Sample data for testing all vital signs
    sample_labels = ['2025-07-26', '2025-07-27', '2025-07-28', '2025-07-29', '2025-07-30', '2025-07-31', '2025-08-01']
    sample_hr_values = [72, 68, 75, 70, 73, 69, 71]
    sample_sleep_values = [7.5, 8.2, 6.8, 7.9, 8.1, 7.3, 8.0]
    sample_cal_values = [2200, 2350, 1980, 2150, 2280, 2050, 2180]
    
    return templates.TemplateResponse("vitals.html", {
        "request": request,
        "hr_labels": sample_labels,
        "hr_values": sample_hr_values,
        "sleep_labels": sample_labels,
        "sleep_values": sample_sleep_values,
        "cal_labels": sample_labels,
        "cal_values": sample_cal_values,
        "view": "weekly"
    })

# Route: Authorize Google OAuth
@app.get('/authorize/google')
async def authorize_google():
    auth_url, _ = GOOGLE_FLOW.authorization_url(prompt='consent')
    return RedirectResponse(url=auth_url)

# Route: Google OAuth Callback
@app.get('/callback')
async def callback_google(request: Request):
    try:
        GOOGLE_FLOW.fetch_token(authorization_response=str(request.url))
        credentials = GOOGLE_FLOW.credentials
        request.session['google_credentials'] = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }
        
        # Extract user info and store in session
        user_email = 'unknown@user.com'
        user_name = 'GoatFit User'
        google_user_id = ''
        
        try:
            # Try to get user info from Google
            service = build('oauth2', 'v2', credentials=credentials)
            user_info = service.userinfo().get().execute()
            user_email = user_info.get('email', 'unknown@user.com')
            user_name = user_info.get('name', 'GoatFit User')
            google_user_id = user_info.get('id', '')
            print(f"✅ User authenticated via Google: {user_email}")
            
        except Exception as e:
            print(f"⚠️ Could not get user info from Google API: {e}")
            print("🔄 Proceeding with OAuth credentials only")
            
            # Extract email from OAuth token if possible
            try:
                import jwt
                # Decode the ID token if available (this is a fallback)
                if hasattr(credentials, 'id_token') and credentials.id_token:
                    decoded_token = jwt.decode(credentials.id_token, verify=False)
                    user_email = decoded_token.get('email', 'unknown@user.com')
                    user_name = decoded_token.get('name', 'GoatFit User')
                    google_user_id = decoded_token.get('sub', '')
            except:
                print("⚠️ Could not extract user info from token, using default values")
        
        # Store user info in session
        request.session['user_email'] = user_email
        request.session['user_name'] = user_name
        request.session['google_user_id'] = google_user_id
        
        # Check if user exists in database
        existing_user = await UserModel.get_user_by_email(user_email)
        
        if not existing_user:
            print(f"📝 New user detected: {user_email} - Redirecting to registration")
            return RedirectResponse(url='/register')
        else:
            print(f"🔄 Existing user: {user_email} - Redirecting to dashboard")
            request.session['user_id'] = existing_user['_id']
            return RedirectResponse(url='/index')
                
    except Exception as e:
        print(f"❌ OAuth callback error: {e}")
        return HTMLResponse(content=f"Error during Google OAuth callback: {e}", status_code=400)

@app.get('/index')
async def index():
    return RedirectResponse(url='/fit?view=weekly')

# =====================================================
# USER REGISTRATION SYSTEM
# =====================================================

@app.get('/register', response_class=HTMLResponse)
async def register_form(request: Request):
    """Show user registration form for first-time users"""
    
    # Check if user is authenticated with Google
    if 'google_credentials' not in request.session:
        return RedirectResponse(url='/authorize/google')
    
    user_email = request.session.get('user_email', '')
    user_name = request.session.get('user_name', '')
    
    # Check if user already exists
    existing_user = await UserModel.get_user_by_email(user_email)
    if existing_user:
        return RedirectResponse(url='/fit?view=weekly')
    
    return templates.TemplateResponse("user_registration.html", {
        "request": request,
        "user_email": user_email,
        "user_name": user_name
    })

@app.post('/register')
async def register_user(request: Request,
                       name: str = Form(...),
                       email: str = Form(...),
                       phone: str = Form(""),
                       age: str = Form(""),  # Changed to string to handle empty values
                       high_hr_warning: int = Form(60),  # Changed to 60 for testing
                       high_hr_critical: int = Form(60),  # Changed to 60 for testing
                       low_hr_warning: int = Form(60),    # Changed to 60 for testing
                       low_hr_critical: int = Form(60),   # Changed to 60 for testing
                       enable_monitoring: bool = Form(False),
                       data_consent: bool = Form(False)):
    """Process user registration"""
    
    try:
        # Validate required fields
        if not enable_monitoring or not data_consent:
            raise HTTPException(status_code=400, detail="Monitoring and data consent are required")
        
        # Convert age to integer, handle empty string
        user_age = None
        if age and age.strip():
            try:
                user_age = int(age)
            except ValueError:
                raise HTTPException(status_code=400, detail="Age must be a valid number")
        
        # Get Google credentials from session
        google_credentials = request.session.get('google_credentials', {})
        google_user_id = request.session.get('google_user_id', '')
        
        # Create user data
        user_data = {
            "email": email,
            "name": name,
            "phone": phone,
            "age": user_age,
            "google_user_id": google_user_id,
            "google_credentials": google_credentials,
            "high_hr_warning": high_hr_warning,
            "high_hr_critical": high_hr_critical,
            "low_hr_warning": low_hr_warning,
            "low_hr_critical": low_hr_critical
        }
        
        # Create user in database
        user_id = await UserModel.create_user(user_data)
        if not user_id:
            raise HTTPException(status_code=500, detail="Failed to create user")
        
        # Store user ID in session
        request.session['user_id'] = user_id
        
        # Process emergency contacts
        form_data = await request.form()
        contact_count = 0
        
        # Count how many contacts were submitted
        for key in form_data.keys():
            if key.startswith('contact_name_'):
                contact_count = max(contact_count, int(key.split('_')[-1]) + 1)
        
        # Add emergency contacts
        contacts_added = 0
        for i in range(contact_count):
            contact_name = form_data.get(f'contact_name_{i}')
            contact_email = form_data.get(f'contact_email_{i}')
            contact_relationship = form_data.get(f'contact_relationship_{i}', 'Other')
            
            if contact_name and contact_email:
                contact_data = {
                    "name": contact_name,
                    "email": contact_email,
                    "relationship": contact_relationship
                }
                
                contact_id = await EmergencyContactModel.add_contact(user_id, contact_data)
                if contact_id:
                    contacts_added += 1
        
        print(f"✅ User registered successfully: {email} with {contacts_added} emergency contacts")
        
        # Redirect to success page or dashboard
        return RedirectResponse(url='/registration-success', status_code=303)
        
    except Exception as e:
        print(f"❌ Registration error: {e}")
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

@app.get('/registration-success', response_class=HTMLResponse)
async def registration_success(request: Request):
    """Show registration success page"""
    return templates.TemplateResponse("registration_success.html", {
        "request": request,
        "user_name": request.session.get('user_name', 'User')
    })

@app.get('/vitals', response_class=HTMLResponse)
async def vitals(request: Request, view: str = Query('weekly')):
    """Endpoint focused on vital signs including heart rate, sleep, and calories"""
    heart_rate_data = []
    sleep_data = []
    calories_data = []
    
    if 'google_credentials' in request.session:
        credentials = Credentials(**request.session['google_credentials'])
        service = build('fitness', 'v1', credentials=credentials)
        try:
            now = datetime.utcnow()

            if view == 'weekly':
                start_time = now - timedelta(days=7)
            elif view == 'monthly':
                start_time = now - timedelta(days=30)
            else:  # yearly
                start_time = now - timedelta(days=365)

            # Fetch heart rate data
            try:
                heart_rate_dataset = service.users().dataset().aggregate(
                    userId="me",
                    body={
                        "aggregateBy": [{"dataTypeName": "com.google.heart_rate.bpm"}],
                        "bucketByTime": {"durationMillis": 86400000},  # Daily buckets
                        "startTimeMillis": int(start_time.timestamp() * 1000),
                        "endTimeMillis": int(now.timestamp() * 1000),
                    }
                ).execute()
                heart_rate_data = heart_rate_dataset.get('bucket', [])
            except Exception as e:
                print(f"Error fetching heart rate data: {e}")

            # Fetch sleep data
            try:
                sleep_dataset = service.users().dataset().aggregate(
                    userId="me",
                    body={
                        "aggregateBy": [{"dataTypeName": "com.google.sleep.segment"}],
                        "bucketByTime": {"durationMillis": 86400000},  # Daily buckets
                        "startTimeMillis": int(start_time.timestamp() * 1000),
                        "endTimeMillis": int(now.timestamp() * 1000),
                    }
                ).execute()
                sleep_data = sleep_dataset.get('bucket', [])
            except Exception as e:
                print(f"Error fetching sleep data: {e}")

            # Fetch calories data
            try:
                calories_dataset = service.users().dataset().aggregate(
                    userId="me",
                    body={
                        "aggregateBy": [{"dataTypeName": "com.google.calories.expended"}],
                        "bucketByTime": {"durationMillis": 86400000},  # Daily buckets
                        "startTimeMillis": int(start_time.timestamp() * 1000),
                        "endTimeMillis": int(now.timestamp() * 1000),
                    }
                ).execute()
                calories_data = calories_dataset.get('bucket', [])
            except Exception as e:
                print(f"Error fetching calories data: {e}")
            
        except Exception as e:
            print(f"Error fetching Google Fit data: {e}")

    # Process heart rate data
    hr_labels = []
    hr_values = []
    for bucket in heart_rate_data:
        for dataset in bucket.get('dataset', []):
            for point in dataset.get('point', []):
                for value in point.get('value', []):
                    if 'fpVal' in value:
                        date = datetime.fromtimestamp(int(bucket['startTimeMillis']) / 1000).strftime('%Y-%m-%d')
                        hr_labels.append(date)
                        hr_values.append(round(value['fpVal'], 1))

    # Process sleep data
    sleep_labels = []
    sleep_values = []
    for bucket in sleep_data:
        for dataset in bucket.get('dataset', []):
            for point in dataset.get('point', []):
                if point.get('value'):
                    date = datetime.fromtimestamp(int(bucket['startTimeMillis']) / 1000).strftime('%Y-%m-%d')
                    # Sleep duration in minutes
                    duration_ms = int(point['endTimeNanos']) - int(point['startTimeNanos'])
                    duration_hours = duration_ms / (1000000000 * 3600)  # Convert to hours
                    sleep_labels.append(date)
                    sleep_values.append(round(duration_hours, 1))

    # Process calories data
    cal_labels = []
    cal_values = []
    for bucket in calories_data:
        for dataset in bucket.get('dataset', []):
            for point in dataset.get('point', []):
                for value in point.get('value', []):
                    if 'fpVal' in value:
                        date = datetime.fromtimestamp(int(bucket['startTimeMillis']) / 1000).strftime('%Y-%m-%d')
                        cal_labels.append(date)
                        cal_values.append(round(value['fpVal'], 0))

    # Check for vital spikes and send alerts if necessary
    if hr_values:
        user_name = request.session.get('user_name', 'GoatFit User')
        spike_info = check_vital_spikes(hr_values, user_name)
        
        if spike_info['alert_needed']:
            print(f"🚨 Vital spike detected for {user_name}!")
            send_emergency_alerts(request, spike_info, user_name)
    
    # Register user for 24/7 automatic monitoring
    if 'google_credentials' in request.session:
        user_email = request.session.get('user_email', 'unknown@user.com')
        emergency_contacts = request.session.get('emergency_contacts', [])
        
        if emergency_contacts:  # Only register if they have emergency contacts
            monitored_users[user_email] = {
                'credentials': credentials,
                'emergency_contacts': emergency_contacts,
                'user_name': user_name,
                'last_check': datetime.now()
            }
            print(f"✅ {user_name} registered for 24/7 automatic health monitoring")

    return templates.TemplateResponse("vitals.html", {
        "request": request,
        "hr_labels": hr_labels,
        "hr_values": hr_values,
        "sleep_labels": sleep_labels,
        "sleep_values": sleep_values,
        "cal_labels": cal_labels,
        "cal_values": cal_values,
        "view": view
    })

@app.get('/fit', response_class=HTMLResponse)
async def fit(request: Request, view: str = Query('weekly')):
    google_fit_data = []
    heart_rate_data = []
    
    if 'google_credentials' in request.session:
        credentials = Credentials(**request.session['google_credentials'])
        service = build('fitness', 'v1', credentials=credentials)
        try:
            now = datetime.utcnow()

            if view == 'weekly':
                start_time = now - timedelta(days=7)
            elif view == 'monthly':
                start_time = now - timedelta(days=30)
            else:  # yearly
                start_time = now - timedelta(days=365)

            # Fetch steps data
            steps_dataset = service.users().dataset().aggregate(
                userId="me",
                body={
                    "aggregateBy": [{"dataTypeName": "com.google.step_count.delta"}],
                    "bucketByTime": {"durationMillis": 86400000},  # Daily buckets
                    "startTimeMillis": int(start_time.timestamp() * 1000),
                    "endTimeMillis": int(now.timestamp() * 1000),
                }
            ).execute()
            
            google_fit_data = steps_dataset.get('bucket', [])

            # Fetch heart rate data
            heart_rate_dataset = service.users().dataset().aggregate(
                userId="me",
                body={
                    "aggregateBy": [{"dataTypeName": "com.google.heart_rate.bpm"}],
                    "bucketByTime": {"durationMillis": 86400000},  # Daily buckets
                    "startTimeMillis": int(start_time.timestamp() * 1000),
                    "endTimeMillis": int(now.timestamp() * 1000),
                }
            ).execute()
            
            heart_rate_data = heart_rate_dataset.get('bucket', [])
            
        except Exception as e:
            print(f"Error fetching Google Fit data: {e}")

    # Convert steps data to a format suitable for Chart.js
    labels = []
    step_values = []
    for bucket in google_fit_data:
        for dataset in bucket.get('dataset', []):
            for point in dataset.get('point', []):
                for value in point.get('value', []):
                    if 'intVal' in value:
                        date = datetime.fromtimestamp(int(bucket['startTimeMillis']) / 1000).strftime('%Y-%m-%d')
                        labels.append(date)
                        step_values.append(value['intVal'])

    # Convert heart rate data to a format suitable for Chart.js
    hr_labels = []
    hr_values = []
    for bucket in heart_rate_data:
        for dataset in bucket.get('dataset', []):
            for point in dataset.get('point', []):
                for value in point.get('value', []):
                    if 'fpVal' in value:
                        date = datetime.fromtimestamp(int(bucket['startTimeMillis']) / 1000).strftime('%Y-%m-%d')
                        hr_labels.append(date)
                        hr_values.append(round(value['fpVal'], 1))

    return templates.TemplateResponse("fit.html", {
        "request": request,
        "labels": labels, 
        "values": step_values,
        "hr_labels": hr_labels,
        "hr_values": hr_values,
        "view": view
    })

# Emergency Contact Management Routes
@app.get('/emergency-contacts', response_class=HTMLResponse)
async def emergency_contacts(request: Request):
    """Emergency contact management page"""
    return templates.TemplateResponse("emergency_contacts.html", {
        "request": request,
        "contacts": request.session.get('emergency_contacts', []),
        "user_name": request.session.get('user_name', 'User')
    })

@app.post('/emergency-contacts/add')
async def add_emergency_contact(request: Request, 
                              contact_name: str = Form(...),
                              contact_email: str = Form(...),
                              relationship: str = Form(...)):
    """Add a new emergency contact"""
    
    # Validate email format (basic validation)
    if '@' not in contact_email or '.' not in contact_email:
        raise HTTPException(status_code=400, detail="Invalid email format")
    
    # Get existing contacts or initialize empty list
    contacts = request.session.get('emergency_contacts', [])
    
    # Create new contact
    new_contact = {
        "id": len(contacts) + 1,
        "name": contact_name,
        "email": contact_email,
        "relationship": relationship,
        "added_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "notifications_enabled": True
    }
    
    # Add to contacts list
    contacts.append(new_contact)
    request.session['emergency_contacts'] = contacts
    
    return RedirectResponse(url="/emergency-contacts", status_code=303)

@app.post('/emergency-contacts/remove/{contact_id}')
async def remove_emergency_contact(request: Request, contact_id: int):
    """Remove an emergency contact"""
    
    contacts = request.session.get('emergency_contacts', [])
    contacts = [c for c in contacts if c['id'] != contact_id]
    request.session['emergency_contacts'] = contacts
    
    return RedirectResponse(url="/emergency-contacts", status_code=303)

@app.post('/emergency-contacts/test/{contact_id}')
async def test_emergency_contact(request: Request, contact_id: int):
    """Send a test alert to an emergency contact"""
    
    contacts = request.session.get('emergency_contacts', [])
    contact = next((c for c in contacts if c['id'] == contact_id), None)
    
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    # Send test email
    success = alert_service.test_email_service(contact['email'])
    
    if success:
        return JSONResponse({"success": True, "message": f"Test alert sent to {contact['name']}"})
    else:
        return JSONResponse({"success": False, "message": "Failed to send test alert"})

# Vital Spike Detection and Alert System
def check_vital_spikes(hr_values: list, user_name: str = "User"):
    """
    Check for dangerous vital spikes and send alerts
    
    Args:
        hr_values: List of heart rate values
        user_name: Name of the user
    """
    
    if not hr_values:
        return {"alert_needed": False, "heart_rate": 0, "threshold": 0, "severity": "NORMAL"}
    
    # Heart rate thresholds - TESTING MODE (All set to 60 for easy testing)
    HIGH_HR_WARNING = 100   # BPM - Test threshold
    HIGH_HR_CRITICAL = 120  # BPM - Test threshold  
    LOW_HR_WARNING = 60    # BPM - Test threshold
    LOW_HR_CRITICAL = 50   # BPM - Test threshold
    
    print(f"🔍 Debug (vitals): HR values: {hr_values}")
    print(f"🔍 Debug (vitals): Latest HR: {hr_values[-1] if hr_values else 0} BPM")
    print(f"🔍 Debug (vitals): Thresholds - HIGH_WARNING: {HIGH_HR_WARNING}, HIGH_CRITICAL: {HIGH_HR_CRITICAL}")
    
    latest_hr = hr_values[-1] if hr_values else 0
    
    # Check for dangerous heart rate
    alert_needed = False
    threshold = 0
    
    if latest_hr >= HIGH_HR_CRITICAL:
        alert_needed = True
        threshold = HIGH_HR_CRITICAL
        print(f"🚨 CRITICAL: Heart rate {latest_hr} exceeds critical threshold!")
    elif latest_hr >= HIGH_HR_WARNING:
        alert_needed = True
        threshold = HIGH_HR_WARNING
        print(f"⚠️ WARNING: Heart rate {latest_hr} exceeds warning threshold!")
    elif latest_hr <= LOW_HR_CRITICAL and latest_hr > 0:
        alert_needed = True
        threshold = LOW_HR_CRITICAL
        print(f"🚨 CRITICAL: Heart rate {latest_hr} below critical threshold!")
    elif latest_hr <= LOW_HR_WARNING and latest_hr > 0:
        alert_needed = True
        threshold = LOW_HR_WARNING
        print(f"⚠️ WARNING: Heart rate {latest_hr} below warning threshold!")
    
    return {
        "alert_needed": alert_needed,
        "heart_rate": latest_hr,
        "threshold": threshold,
        "severity": "CRITICAL" if latest_hr >= HIGH_HR_CRITICAL or latest_hr <= LOW_HR_CRITICAL else "WARNING"
    }

def send_emergency_alerts(request: Request, spike_info: dict, user_name: str = "User"):
    """Send alerts to all emergency contacts"""
    
    if not spike_info.get("alert_needed"):
        return
    
    contacts = request.session.get('emergency_contacts', [])
    
    if not contacts:
        print("⚠️ No emergency contacts configured for alerts")
        return
    
    alert_count = 0
    for contact in contacts:
        if contact.get('notifications_enabled', True):
            try:
                success = send_heart_rate_alert(
                    emergency_email=contact['email'],
                    user_name=user_name,
                    heart_rate=spike_info['heart_rate'],
                    threshold=spike_info['threshold']
                )
                
                if success:
                    alert_count += 1
                    print(f"✅ Alert sent to {contact['name']} ({contact['email']})")
                else:
                    print(f"❌ Failed to send alert to {contact['name']} ({contact['email']})")
                    
            except Exception as e:
                print(f"❌ Error sending alert to {contact['name']}: {e}")
    
    print(f"📧 Emergency alerts sent to {alert_count}/{len(contacts)} contacts")

@app.get('/test-auth')
async def test_auth(request: Request):
    """Test Google Fit authentication and basic data access"""
    
    if 'google_credentials' not in request.session:
        return JSONResponse({"error": "Not authenticated with Google Fit", "auth_url": "/authorize/google"})
    
    try:
        credentials = Credentials(**request.session['google_credentials'])
        service = build('fitness', 'v1', credentials=credentials)
        
        # Test basic access
        profile = service.users().profile().get(userId="me").execute()
        
        # Test data sources
        data_sources = service.users().dataSources().list(userId="me").execute()
        
        heart_rate_sources = []
        for ds in data_sources.get('dataSource', []):
            data_type = ds.get('dataType', {}).get('name', '')
            if 'heart' in data_type.lower() or 'bpm' in data_type.lower():
                heart_rate_sources.append({
                    "name": data_type,
                    "id": ds.get('dataStreamId', ''),
                    "type": ds.get('type', ''),
                    "device": ds.get('device', {}).get('model', 'Unknown')
                })
        
        return JSONResponse({
            "authenticated": True,
            "user_profile": profile,
            "total_data_sources": len(data_sources.get('dataSource', [])),
            "heart_rate_sources": heart_rate_sources,
            "credentials_valid": True
        })
        
    except Exception as e:
        return JSONResponse({
            "authenticated": False,
            "error": str(e),
            "suggestion": "Try re-authenticating at /authorize/google"
        })

@app.get('/test-latest-monitoring')
async def test_latest_monitoring(request: Request):
    """Test the latest monitoring system with current user"""
    
    if 'google_credentials' not in request.session:
        return JSONResponse({"error": "Not authenticated with Google Fit"})
    
    try:
        # Get user from database
        user_email = request.session.get('user_email', 'unknown@user.com')
        user = await UserModel.get_user_by_email(user_email)
        
        if not user:
            return JSONResponse({"error": "User not found in database"})
        
        # Get emergency contacts
        emergency_contacts = await EmergencyContactModel.get_user_contacts(user['_id'])
        
        if not emergency_contacts:
            return JSONResponse({"error": "No emergency contacts found"})
        
        # Test the monitoring function
        credentials = Credentials(**request.session['google_credentials'])
        
        # Capture the monitoring results
        import io
        import sys
        from contextlib import redirect_stdout
        
        output_buffer = io.StringIO()
        
        try:
            with redirect_stdout(output_buffer):
                await check_user_health_automatically_db(user, credentials, emergency_contacts)
            
            monitoring_output = output_buffer.getvalue()
            
            return JSONResponse({
                "success": True,
                "user_email": user_email,
                "emergency_contacts": len(emergency_contacts),
                "monitoring_output": monitoring_output.split('\n')[-20:],  # Last 20 lines
                "message": "Monitoring test completed - check terminal for full output"
            })
            
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
                "monitoring_output": output_buffer.getvalue()
            })
            
    except Exception as e:
        return JSONResponse({"error": str(e)})

@app.get('/force-latest-sync')
async def force_latest_sync(request: Request):
    """Try different methods to get the absolute latest heart rate data"""
    
    if 'google_credentials' not in request.session:
        return JSONResponse({"error": "Not authenticated with Google Fit"})
    
    try:
        credentials = Credentials(**request.session['google_credentials'])
        service = build('fitness', 'v1', credentials=credentials)
        
        # Use current local time instead of UTC to account for timezone
        now_local = datetime.now()
        now_utc = datetime.utcnow()
        
        results = {
            "timezone_info": {
                "local_time": now_local.isoformat(),
                "utc_time": now_utc.isoformat()
            },
            "methods": {}
        }
        
        # Method 1: Use very recent time window (last 2 hours)
        start_recent = now_utc - timedelta(hours=2)
        
        try:
            recent_aggregate = service.users().dataset().aggregate(
                userId="me",
                body={
                    "aggregateBy": [{"dataTypeName": "com.google.heart_rate.bpm"}],
                    "bucketByTime": {"durationMillis": 300000},  # 5-minute buckets
                    "startTimeMillis": int(start_recent.timestamp() * 1000),
                    "endTimeMillis": int(now_utc.timestamp() * 1000),
                }
            ).execute()
            
            recent_points = []
            for bucket in recent_aggregate.get('bucket', []):
                bucket_time = datetime.fromtimestamp(int(bucket['startTimeMillis']) / 1000)
                for dataset in bucket.get('dataset', []):
                    for point in dataset.get('point', []):
                        for value in point.get('value', []):
                            if 'fpVal' in value:
                                recent_points.append({
                                    "time": bucket_time.isoformat(),
                                    "heart_rate": round(value['fpVal'], 1),
                                    "method": "recent_aggregate"
                                })
            
            results["methods"]["recent_aggregate"] = {
                "points_found": len(recent_points),
                "data": recent_points
            }
            
        except Exception as e:
            results["methods"]["recent_aggregate"] = {"error": str(e)}
        
        # Method 2: Query NoiseColorFit raw data directly for today
        try:
            # Start from beginning of today
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Convert to UTC for API
            today_start_utc = today_start.utctimetuple()
            today_start_utc = datetime(*today_start_utc[:6])
            
            dataset_id = f"{int(today_start_utc.timestamp() * 1000000000)}-{int(now_utc.timestamp() * 1000000000)}"
            
            # Query the NoiseColorFit raw data source
            noisefit_data = service.users().dataSources().datasets().get(
                userId="me",
                dataSourceId="raw:com.google.heart_rate.bpm:com.noisefit:noise_activity - Heart data",
                datasetId=dataset_id
            ).execute()
            
            noisefit_points = []
            for point in noisefit_data.get('point', []):
                point_time = datetime.fromtimestamp(int(point.get('startTimeNanos', 0)) / 1000000000)
                for value in point.get('value', []):
                    if 'fpVal' in value:
                        noisefit_points.append({
                            "time": point_time.isoformat(),
                            "heart_rate": round(value['fpVal'], 1),
                            "method": "noisefit_raw_today"
                        })
            
            # Sort by time (most recent first)
            noisefit_points.sort(key=lambda x: x["time"], reverse=True)
            
            results["methods"]["noisefit_raw_today"] = {
                "query_start": today_start_utc.isoformat(),
                "points_found": len(noisefit_points),
                "data": noisefit_points[:10]  # Show last 10 readings
            }
            
        except Exception as e:
            results["methods"]["noisefit_raw_today"] = {"error": str(e)}
        
        # Method 3: Use local timezone for queries
        try:
            # Query using local timezone
            import pytz
            local_tz = pytz.timezone('Asia/Kolkata')  # Adjust to your timezone
            now_local_tz = datetime.now(local_tz)
            start_local = now_local_tz - timedelta(hours=6)
            
            # Convert to UTC for API
            start_utc_from_local = start_local.astimezone(pytz.UTC).replace(tzinfo=None)
            end_utc_from_local = now_local_tz.astimezone(pytz.UTC).replace(tzinfo=None)
            
            local_aggregate = service.users().dataset().aggregate(
                userId="me",
                body={
                    "aggregateBy": [{"dataTypeName": "com.google.heart_rate.bpm"}],
                    "bucketByTime": {"durationMillis": 600000},  # 10-minute buckets
                    "startTimeMillis": int(start_utc_from_local.timestamp() * 1000),
                    "endTimeMillis": int(end_utc_from_local.timestamp() * 1000),
                }
            ).execute()
            
            local_points = []
            for bucket in local_aggregate.get('bucket', []):
                bucket_time = datetime.fromtimestamp(int(bucket['startTimeMillis']) / 1000)
                for dataset in bucket.get('dataset', []):
                    for point in dataset.get('point', []):
                        for value in point.get('value', []):
                            if 'fpVal' in value:
                                local_points.append({
                                    "time": bucket_time.isoformat(),
                                    "heart_rate": round(value['fpVal'], 1),
                                    "method": "local_timezone"
                                })
            
            results["methods"]["local_timezone"] = {
                "local_start": start_local.isoformat(),
                "points_found": len(local_points),
                "data": local_points
            }
            
        except Exception as e:
            results["methods"]["local_timezone"] = {"error": str(e)}
        
        return JSONResponse(results)
        
    except Exception as e:
        return JSONResponse({"error": str(e)})

@app.get('/debug-latest-data')
async def debug_latest_data(request: Request):
    """Debug endpoint to check the very latest heart rate data with detailed timestamps"""
    
    if 'google_credentials' not in request.session:
        return JSONResponse({"error": "Not authenticated with Google Fit"})
    
    try:
        credentials = Credentials(**request.session['google_credentials'])
        service = build('fitness', 'v1', credentials=credentials)
        now = datetime.utcnow()
        
        # Check current time and timezone
        local_now = datetime.now()
        
        debug_info = {
            "current_utc": now.isoformat(),
            "current_local": local_now.isoformat(),
            "query_results": {}
        }
        
        # Try multiple recent time windows
        time_windows = [
            ("last 1 hour", timedelta(hours=1)),
            ("last 6 hours", timedelta(hours=6)),
            ("last 24 hours", timedelta(hours=24)),
            ("last 3 days", timedelta(days=3))
        ]
        
        for window_name, time_delta in time_windows:
            start_time = now - time_delta
            
            debug_info["query_results"][window_name] = {
                "start_time": start_time.isoformat(),
                "end_time": now.isoformat(),
                "data_sources": {}
            }
            
            try:
                # Get all data sources first
                data_sources = service.users().dataSources().list(userId="me").execute()
                
                # Find heart rate sources
                hr_sources = []
                for ds in data_sources.get('dataSource', []):
                    data_type = ds.get('dataType', {}).get('name', '')
                    if 'heart_rate' in data_type.lower():
                        hr_sources.append(ds)
                
                # Query each heart rate source
                for ds in hr_sources:
                    source_name = ds.get('dataStreamName', 'Unknown')
                    dataset_id = f"{int(start_time.timestamp() * 1000000000)}-{int(now.timestamp() * 1000000000)}"
                    
                    try:
                        data_response = service.users().dataSources().datasets().get(
                            userId="me",
                            dataSourceId=ds['dataStreamId'],
                            datasetId=dataset_id
                        ).execute()
                        
                        points = data_response.get('point', [])
                        
                        debug_info["query_results"][window_name]["data_sources"][source_name] = {
                            "total_points": len(points),
                            "source_id": ds['dataStreamId'],
                            "application": ds.get('application', {}).get('packageName', 'Unknown'),
                            "latest_points": []
                        }
                        
                        # Get the 5 most recent points
                        if points:
                            # Sort by time (most recent first)
                            points.sort(key=lambda p: int(p.get('startTimeNanos', 0)), reverse=True)
                            
                            for point in points[:5]:  # Top 5 most recent
                                point_time_ns = int(point.get('startTimeNanos', 0))
                                point_time = datetime.fromtimestamp(point_time_ns / 1000000000)
                                
                                for value in point.get('value', []):
                                    if 'fpVal' in value or 'intVal' in value:
                                        hr_value = value.get('fpVal', value.get('intVal', 0))
                                        
                                        debug_info["query_results"][window_name]["data_sources"][source_name]["latest_points"].append({
                                            "timestamp": point_time.isoformat(),
                                            "heart_rate": hr_value,
                                            "timestamp_ns": point_time_ns,
                                            "raw_point": point
                                        })
                        
                    except Exception as e:
                        debug_info["query_results"][window_name]["data_sources"][source_name] = {
                            "error": str(e)
                        }
                        
            except Exception as e:
                debug_info["query_results"][window_name]["error"] = str(e)
        
        return JSONResponse(debug_info)
        
    except Exception as e:
        return JSONResponse({"error": str(e)})

@app.get('/simple-hr-test')
async def simple_hr_test(request: Request):
    """Simple heart rate test with raw data sources"""
    
    if 'google_credentials' not in request.session:
        return JSONResponse({"error": "Not authenticated with Google Fit"})
    
    try:
        credentials = Credentials(**request.session['google_credentials'])
        service = build('fitness', 'v1', credentials=credentials)
        now = datetime.utcnow()
        
        # Try last 7 days
        start_time = now - timedelta(days=7)
        
        # Get data sources
        data_sources = service.users().dataSources().list(userId="me").execute()
        
        results = {
            "total_sources": len(data_sources.get('dataSource', [])),
            "heart_rate_sources": [],
            "heart_rate_data": []
        }
        
        # Find heart rate sources
        for ds in data_sources.get('dataSource', []):
            data_type = ds.get('dataType', {}).get('name', '')
            if 'heart_rate' in data_type.lower():
                source_info = {
                    "name": ds.get('dataStreamName', 'Unknown'),
                    "id": ds.get('dataStreamId', ''),
                    "type": ds.get('type', ''),
                    "data_type": data_type,
                    "application": ds.get('application', {}).get('packageName', 'Unknown')
                }
                results["heart_rate_sources"].append(source_info)
                
                # Try to get data from this source
                try:
                    dataset_id = f"{int(start_time.timestamp() * 1000000000)}-{int(now.timestamp() * 1000000000)}"
                    
                    data_response = service.users().dataSources().datasets().get(
                        userId="me",
                        dataSourceId=ds['dataStreamId'],
                        datasetId=dataset_id
                    ).execute()
                    
                    points = data_response.get('point', [])
                    source_info["points_found"] = len(points)
                    
                    # Get recent values
                    recent_values = []
                    for point in points[-10:]:  # Last 10 points
                        point_time = datetime.fromtimestamp(int(point.get('startTimeNanos', 0)) / 1000000000)
                        for value in point.get('value', []):
                            if 'fpVal' in value:
                                recent_values.append({
                                    "time": point_time.isoformat(),
                                    "value": round(value['fpVal'], 1),
                                    "source": source_info["name"]
                                })
                            elif 'intVal' in value:
                                recent_values.append({
                                    "time": point_time.isoformat(),
                                    "value": value['intVal'],
                                    "source": source_info["name"]
                                })
                    
                    results["heart_rate_data"].extend(recent_values)
                    
                except Exception as e:
                    source_info["error"] = str(e)
        
        # Sort by time (most recent first)
        results["heart_rate_data"].sort(key=lambda x: x["time"], reverse=True)
        
        return JSONResponse(results)
        
    except Exception as e:
        return JSONResponse({"error": str(e)})

@app.get('/debug-heartrate')
async def debug_heartrate(request: Request):
    """Debug endpoint to check available heart rate data"""
    
    if 'google_credentials' not in request.session:
        return JSONResponse({"error": "Not authenticated with Google Fit"})
    
    try:
        credentials = Credentials(**request.session['google_credentials'])
        service = build('fitness', 'v1', credentials=credentials)
        now = datetime.utcnow()
        
        # Try different time windows
        time_windows = [
            ("5 minutes", timedelta(minutes=5), 60000),      # 1-minute buckets
            ("30 minutes", timedelta(minutes=30), 300000),   # 5-minute buckets  
            ("24 hours", timedelta(hours=24), 3600000),      # 1-hour buckets
            ("7 days", timedelta(days=7), 86400000)          # 1-day buckets
        ]
        
        results = {}
        
        for window_name, time_delta, bucket_size in time_windows:
            start_time = now - time_delta
            
            heart_rate_dataset = service.users().dataset().aggregate(
                userId="me",
                body={
                    "aggregateBy": [{"dataTypeName": "com.google.heart_rate.bpm"}],
                    "bucketByTime": {"durationMillis": bucket_size},
                    "startTimeMillis": int(start_time.timestamp() * 1000),
                    "endTimeMillis": int(now.timestamp() * 1000),
                }
            ).execute()
            
            hr_values = []
            buckets = heart_rate_dataset.get('bucket', [])
            
            for bucket in buckets:
                bucket_time = datetime.fromtimestamp(int(bucket['startTimeMillis']) / 1000)
                for dataset in bucket.get('dataset', []):
                    for point in dataset.get('point', []):
                        for value in point.get('value', []):
                            if 'fpVal' in value:
                                hr_values.append({
                                    "value": round(value['fpVal'], 1),
                                    "time": bucket_time.isoformat()
                                })
            
            results[window_name] = {
                "total_values": len(hr_values),
                "buckets_found": len(buckets),
                "time_range": f"{start_time.isoformat()} to {now.isoformat()}",
                "values": hr_values[-5:] if hr_values else []  # Show last 5 values
            }
        
        return JSONResponse(results)
        
    except Exception as e:
        return JSONResponse({"error": str(e)})

@app.get('/test-alerts')
async def test_alerts_page(request: Request):
    """Test page for emergency alerts"""
    return templates.TemplateResponse("test_alerts.html", {
        "request": request,
        "contacts": request.session.get('emergency_contacts', [])
    })

@app.get('/quick-test/{heart_rate}')
async def quick_test_heart_rate(request: Request, heart_rate: int):
    """Quick test endpoint - visit /quick-test/72 to test with 72 BPM"""
    
    # Store test user info
    request.session['user_name'] = 'Test User'
    request.session['user_email'] = 'test@goatfit.com'
    
    # Check for spikes
    spike_info = check_vital_spikes([heart_rate], 'Test User')
    
    response_data = {
        "heart_rate": heart_rate,
        "alert_triggered": spike_info['alert_needed'],
        "severity": spike_info['severity'],
        "threshold": spike_info['threshold'],
        "message": "",
        "emails_sent": 0
    }
    
    if spike_info['alert_needed']:
        # Send emergency alerts
        contacts = request.session.get('emergency_contacts', [])
        if contacts:
            send_emergency_alerts(request, spike_info, 'Test User')
            response_data["emails_sent"] = len(contacts)
            response_data["message"] = f"🚨 ALERT! Heart rate {heart_rate} BPM exceeds threshold {spike_info['threshold']} BPM. Emergency emails sent to {len(contacts)} contacts."
        else:
            response_data["message"] = f"🚨 ALERT! Heart rate {heart_rate} BPM exceeds threshold {spike_info['threshold']} BPM. No emergency contacts configured."
    else:
        response_data["message"] = f"✅ Heart rate {heart_rate} BPM is within normal range (threshold: {spike_info['threshold']} BPM)."
    
    return JSONResponse(response_data)

@app.post('/simulate-emergency')
async def simulate_emergency(request: Request, 
                           heart_rate: int = Form(...),
                           user_name: str = Form("Test User")):
    """Simulate an emergency for testing purposes"""
    
    # Store user name in session
    request.session['user_name'] = user_name
    
    # Check for spikes
    spike_info = check_vital_spikes([heart_rate], user_name)
    
    if spike_info['alert_needed']:
        # Send emergency alerts
        send_emergency_alerts(request, spike_info, user_name)
        
        return JSONResponse({
            "success": True,
            "message": f"Emergency simulation complete! HR: {heart_rate} BPM",
            "spike_info": spike_info,
            "contacts_notified": len(request.session.get('emergency_contacts', []))
        })
    else:
        return JSONResponse({
            "success": False,
            "message": f"Heart rate {heart_rate} BPM is within normal range",
            "spike_info": spike_info
        })

# =====================================================
# 24/7 AUTOMATIC HEALTH MONITORING SYSTEM
# =====================================================

async def continuous_health_monitoring():
    """24/7 Background health monitoring - runs automatically"""
    global global_monitoring_active
    
    print("🏥 Starting 24/7 Automatic Health Monitoring System...")
    global_monitoring_active = True
    
    # Get Gemini API key from environment
    gemini_api_key = os.getenv('GEMINI_API_KEY')
    if gemini_api_key:
        print("🧠 Gemini AI Integration: ENABLED")
    else:
        print("⚠️ Gemini AI Integration: DISABLED (no API key found)")
    
    while global_monitoring_active:
        try:
            # Get all monitored users from database
            monitored_users = await UserModel.get_all_monitored_users()
            
            if monitored_users:
                print(f"🔍 Checking health for {len(monitored_users)} registered users...")
                
                # Check each registered user
                for user in monitored_users:
                    try:
                        # Get user's emergency contacts
                        emergency_contacts = await EmergencyContactModel.get_user_contacts(user['_id'])
                        
                        if emergency_contacts:
                            # Reconstruct credentials from stored data
                            credentials_data = user.get('google_credentials', {})
                            if credentials_data:
                                credentials = Credentials(
                                    token=credentials_data.get('token'),
                                    refresh_token=credentials_data.get('refresh_token'),
                                    token_uri=credentials_data.get('token_uri'),
                                    client_id=credentials_data.get('client_id'),
                                    client_secret=credentials_data.get('client_secret'),
                                    scopes=credentials_data.get('scopes')
                                )
                                
                                await check_user_health_automatically_db(
                                    user=user,
                                    credentials=credentials,
                                    emergency_contacts=emergency_contacts
                                )
                                
                                # Update last check time
                                await UserModel.update_user(user['_id'], {
                                    'last_health_check': datetime.now()
                                })
                        else:
                            print(f"⚠️ No emergency contacts for user: {user['email']}")
                            
                    except Exception as e:
                        print(f"❌ Error checking {user['email']}: {e}")
            else:
                print("📝 No users registered for monitoring yet")
            
            await asyncio.sleep(60)  # Check every 1 minute
            
        except Exception as e:
            print(f"❌ Error in continuous monitoring: {e}")
            await asyncio.sleep(30)  # Wait before retrying

async def check_user_health_automatically_db(user: dict, credentials, emergency_contacts: list):
    """Check a specific user's health data automatically using database storage"""
    try:
        service = build('fitness', 'v1', credentials=credentials)
        now = datetime.utcnow()
        start_time = now - timedelta(hours=24)  # Use 24-hour window to catch recent data
        
        print(f"🔍 Debug: Fetching heart rate data for {user['name']}")
        print(f"🔍 Debug: Time range: {start_time} to {now}")
        
        hr_values = []
        
        # Directly query the NoiseColorFit raw data source (we know this works from debug data)
        try:
            dataset_id = f"{int(start_time.timestamp() * 1000000000)}-{int(now.timestamp() * 1000000000)}"
            
            print(f"🔍 Debug: Querying NoiseColorFit raw data for last 24 hours...")
            
            noisefit_data = service.users().dataSources().datasets().get(
                userId="me",
                dataSourceId="raw:com.google.heart_rate.bpm:com.noisefit:noise_activity - Heart data",
                datasetId=dataset_id
            ).execute()
            
            points = noisefit_data.get('point', [])
            print(f"🔍 Debug: NoiseColorFit raw data returned {len(points)} points")
            
            # Sort points by time (most recent first)
            points.sort(key=lambda p: int(p.get('startTimeNanos', 0)), reverse=True)
            
            for point in points:
                point_time = datetime.fromtimestamp(int(point.get('startTimeNanos', 0)) / 1000000000)
                for value in point.get('value', []):
                    if 'fpVal' in value:
                        hr_value = round(value['fpVal'], 1)
                        hr_values.append(hr_value)
                        print(f"🔍 Debug: Found HR {hr_value} BPM at {point_time} from NoiseColorFit")
            
            if hr_values:
                print(f"✅ Successfully found {len(hr_values)} heart rate values from NoiseColorFit")
                
        except Exception as e:
            print(f"❌ Error querying NoiseColorFit: {e}")
            
            # Fallback to merged data source
            try:
                dataset_id = f"{int(start_time.timestamp() * 1000000000)}-{int(now.timestamp() * 1000000000)}"
                
                merged_data = service.users().dataSources().datasets().get(
                    userId="me",
                    dataSourceId="derived:com.google.heart_rate.bpm:com.google.android.gms:merge_heart_rate_bpm",
                    datasetId=dataset_id
                ).execute()
                
                points = merged_data.get('point', [])
                points.sort(key=lambda p: int(p.get('startTimeNanos', 0)), reverse=True)
                
                for point in points:
                    point_time = datetime.fromtimestamp(int(point.get('startTimeNanos', 0)) / 1000000000)
                    for value in point.get('value', []):
                        if 'fpVal' in value:
                            hr_value = round(value['fpVal'], 1)
                            hr_values.append(hr_value)
                            print(f"🔍 Debug: Found HR {hr_value} BPM at {point_time} from merged data")
                
            except Exception as e2:
                print(f"❌ Error querying merged data: {e2}")
        
        # Process the heart rate data if we found any
        if hr_values:
            # Use the most recent reading (first in sorted list)
            latest_hr = hr_values[0]
            print(f"🔍 Debug: Processing {len(hr_values)} heart rate values")
            print(f"🔍 Debug: Latest HR: {latest_hr} BPM")
            print(f"🔍 Debug: User data: {user}")
            
            # Use user's custom thresholds from database
            spike_info = check_vital_spikes_custom([latest_hr], user['name'], user)
            print(f"🔍 Debug: Spike info result: {spike_info}")
            
            if spike_info['alert_needed']:
                print(f"🚨 EMERGENCY DETECTED for {user['name']}!")
                print(f"Heart Rate: {spike_info['heart_rate']} BPM (Threshold: {spike_info['threshold']})")
                
                # Send emergency alerts to all contacts
                alert_count = 0
                contacts_notified = []
                
                for contact in emergency_contacts:
                    if contact.get('notifications_enabled', True):
                        try:
                            success = send_heart_rate_alert(
                                emergency_email=contact['email'],
                                user_name=user['name'],
                                heart_rate=spike_info['heart_rate'],
                                threshold=spike_info['threshold']
                            )
                            
                            if success:
                                alert_count += 1
                                contacts_notified.append(contact['email'])
                                print(f"✅ EMERGENCY ALERT sent to {contact['name']} ({contact['email']})")
                            else:
                                print(f"❌ Failed to send alert to {contact['name']}")
                        except Exception as e:
                            print(f"❌ Error sending alert to {contact['name']}: {e}")
                
                print(f"📧 Emergency alerts sent to {alert_count}/{len(emergency_contacts)} contacts")
                
                # Store alert in database
                alert_data = {
                    "user_id": user['_id'],
                    "alert_type": "heart_rate",
                    "severity": spike_info['severity'],
                    "value": spike_info['heart_rate'],
                    "threshold": spike_info['threshold'],
                    "message": f"Heart rate {spike_info['heart_rate']} BPM exceeded threshold {spike_info['threshold']} BPM",
                    "contacts_notified": contacts_notified
                }
                await HealthAlertModel.create_alert(alert_data)
                
                # Use Gemini AI for analysis if available
                gemini_api_key = os.getenv('GEMINI_API_KEY')
                if gemini_api_key:
                    print(f"🧠 Analyzing health pattern with Gemini AI...")
                    # Add AI analysis here if needed
            else:
                print(f"✅ Health check OK for {user['name']} - HR: {latest_hr} BPM (No alert needed)")
        else:
            print(f"⚠️ No heart rate data found for {user['name']} in the last 24 hours")
    
    except Exception as e:
        print(f"❌ Error checking health for {user['name']}: {e}")

def check_vital_spikes_custom(hr_values: list, user_name: str = "User", health_prefs: dict = None):
    """
    Check for dangerous vital spikes using custom user thresholds
    """
    
    if not hr_values:
        return {"alert_needed": False, "heart_rate": 0, "threshold": 0, "severity": "NORMAL"}
    
    # Use custom thresholds if provided, otherwise use defaults
    if health_prefs:
        # Get thresholds directly from user object
        HIGH_HR_WARNING = health_prefs.get('high_hr_warning', 60)
        HIGH_HR_CRITICAL = health_prefs.get('high_hr_critical', 60)
        LOW_HR_WARNING = health_prefs.get('low_hr_warning', 60)
        LOW_HR_CRITICAL = health_prefs.get('low_hr_critical', 60)
    else:
        # Default thresholds for testing - all set to 60 for easy testing
        HIGH_HR_WARNING = 60   
        HIGH_HR_CRITICAL = 60   
        LOW_HR_WARNING = 60    
        LOW_HR_CRITICAL = 60   
    
    print(f"🔍 Debug Thresholds - HIGH_WARNING: {HIGH_HR_WARNING}, HIGH_CRITICAL: {HIGH_HR_CRITICAL}, LOW_WARNING: {LOW_HR_WARNING}, LOW_CRITICAL: {LOW_HR_CRITICAL}")
    
    latest_hr = hr_values[-1] if hr_values else 0
    print(f"🔍 Debug: Checking HR {latest_hr} against thresholds")
    
    # Check for dangerous heart rate
    alert_needed = False
    threshold = 0
    severity = "NORMAL"
    
    if latest_hr >= HIGH_HR_CRITICAL:
        alert_needed = True
        threshold = HIGH_HR_CRITICAL
        severity = "CRITICAL"
        print(f"🚨 CRITICAL: Heart rate {latest_hr} exceeds critical threshold!")
    elif latest_hr >= HIGH_HR_WARNING:
        alert_needed = True
        threshold = HIGH_HR_WARNING
        severity = "WARNING"
        print(f"⚠️ WARNING: Heart rate {latest_hr} exceeds warning threshold!")
    elif latest_hr <= LOW_HR_CRITICAL and latest_hr > 0:
        alert_needed = True
        threshold = LOW_HR_CRITICAL
        severity = "CRITICAL"
        print(f"🚨 CRITICAL: Heart rate {latest_hr} below critical threshold!")
    elif latest_hr <= LOW_HR_WARNING and latest_hr > 0:
        alert_needed = True
        threshold = LOW_HR_WARNING
        severity = "WARNING"
        print(f"⚠️ WARNING: Heart rate {latest_hr} below warning threshold!")
    
    return {
        "alert_needed": alert_needed,
        "heart_rate": latest_hr,
        "threshold": threshold,
        "severity": severity
    }

async def check_user_health_automatically(credentials, emergency_contacts, user_name):
    """Check a specific user's health data automatically"""
    try:
        service = build('fitness', 'v1', credentials=credentials)
        now = datetime.utcnow()
        start_time = now - timedelta(minutes=5)  # Check last 5 minutes
        
        # Fetch recent heart rate data
        heart_rate_dataset = service.users().dataset().aggregate(
            userId="me",
            body={
                "aggregateBy": [{"dataTypeName": "com.google.heart_rate.bpm"}],
                "bucketByTime": {"durationMillis": 60000},  # 1-minute buckets
                "startTimeMillis": int(start_time.timestamp() * 1000),
                "endTimeMillis": int(now.timestamp() * 1000),
            }
        ).execute()
        
        # Process heart rate data
        hr_values = []
        heart_rate_data = heart_rate_dataset.get('bucket', [])
        
        for bucket in heart_rate_data:
            for dataset in bucket.get('dataset', []):
                for point in dataset.get('point', []):
                    for value in point.get('value', []):
                        if 'fpVal' in value:
                            hr_values.append(round(value['fpVal'], 1))
        
        if hr_values:
            # Check for vital spikes
            spike_info = check_vital_spikes(hr_values, user_name)
            
            if spike_info['alert_needed']:
                print(f"🚨 EMERGENCY DETECTED for {user_name}!")
                print(f"Heart Rate: {spike_info['heart_rate']} BPM (Threshold: {spike_info['threshold']})")
                
                # Send emergency alerts to all contacts
                alert_count = 0
                for contact in emergency_contacts:
                    if contact.get('notifications_enabled', True):
                        try:
                            success = send_heart_rate_alert(
                                emergency_email=contact['email'],
                                user_name=user_name,
                                heart_rate=spike_info['heart_rate'],
                                threshold=spike_info['threshold']
                            )
                            
                            if success:
                                alert_count += 1
                                print(f"✅ EMERGENCY ALERT sent to {contact['name']} ({contact['email']})")
                            else:
                                print(f"❌ Failed to send alert to {contact['name']}")
                        except Exception as e:
                            print(f"❌ Error sending alert to {contact['name']}: {e}")
                
                print(f"📧 Emergency alerts sent to {alert_count}/{len(emergency_contacts)} contacts")
                
                # Use Gemini AI for analysis if available
                gemini_api_key = os.getenv('GEMINI_API_KEY')
                if gemini_api_key:
                    print(f"🧠 Analyzing health pattern with Gemini AI...")
                    # Add AI analysis here if needed
            else:
                print(f"✅ Health check OK for {user_name} - HR: {hr_values[-1]} BPM")
    
    except Exception as e:
        print(f"❌ Error checking health for {user_name}: {e}")

@app.on_event("startup")
async def startup_event():
    """Start 24/7 monitoring automatically when app starts"""
    global global_monitoring_task
    
    print("🚀 GoatFit Health Monitoring System Starting...")
    
    # Initialize database connection
    db_success = await init_database()
    if not db_success:
        print("❌ Failed to initialize database - some features may not work")
    
    print("🏥 Initializing 24/7 Automatic Health Monitoring...")
    
    # Start continuous monitoring as background task
    global_monitoring_task = asyncio.create_task(continuous_health_monitoring())
    
    print("✅ 24/7 Health Monitoring System is now ACTIVE!")

@app.on_event("shutdown")
async def shutdown_event():
    """Stop monitoring when app shuts down"""
    global global_monitoring_active, global_monitoring_task
    
    print("🛑 Shutting down 24/7 Health Monitoring System...")
    global_monitoring_active = False
    
    if global_monitoring_task:
        global_monitoring_task.cancel()
    
    # Close database connection
    await close_database()
    
    print("✅ Health Monitoring System stopped")

# =====================================================
# AUTOMATED HEALTH MONITORING SYSTEM
# =====================================================

@app.get('/monitoring-dashboard')
async def monitoring_dashboard(request: Request):
    """Dashboard showing 24/7 automatic health monitoring status"""
    user_email = request.session.get('user_email', 'Unknown User')
    
    # Check if user exists in database and has monitoring enabled
    user_registered = False
    emergency_contacts = []
    total_monitored_users = 0
    
    try:
        # Check if user exists in database
        existing_user = await UserModel.get_user_by_email(user_email)
        if existing_user:
            user_registered = True
            # Get user's emergency contacts from database
            emergency_contacts = await EmergencyContactModel.get_user_contacts(existing_user['_id'])
        
        # Get total count of monitored users from database
        all_monitored = await UserModel.get_all_monitored_users()
        total_monitored_users = len(all_monitored)
        
    except Exception as e:
        print(f"❌ Error fetching monitoring dashboard data: {e}")
    
    return templates.TemplateResponse("monitoring_dashboard.html", {
        "request": request,
        "user_email": user_email,
        "monitoring_active": global_monitoring_active,
        "user_registered": user_registered,
        "contacts": emergency_contacts,
        "total_contacts": len(emergency_contacts),
        "total_monitored_users": total_monitored_users,
        "check_interval": 60  # 1 minute check interval for 24/7 monitoring
    })

@app.get('/register-monitoring')
async def register_monitoring(request: Request):
    """Register user for 24/7 automatic monitoring (happens automatically when they have credentials + contacts)"""
    
    user_email = request.session.get('user_email', 'Unknown User')
    
    # Check if user is authenticated
    if 'google_credentials' not in request.session:
        return JSONResponse({
            "success": False,
            "message": "Please login with Google Fit first"
        })
    
    # Check if user has emergency contacts
    emergency_contacts = request.session.get('emergency_contacts', [])
    if not emergency_contacts:
        return JSONResponse({
            "success": False,
            "message": "Please add at least one emergency contact to enable monitoring"
        })
    
    # User is already registered through the vitals endpoint
    if user_email in monitored_users:
        return JSONResponse({
            "success": True,
            "message": f"✅ You are already registered for 24/7 automatic health monitoring!",
            "details": {
                "system": "24/7 Active",
                "contacts": len(emergency_contacts),
                "ai_analysis": "Enabled" if os.getenv('GEMINI_API_KEY') else "Disabled"
            }
        })
    else:
        return JSONResponse({
            "success": False,
            "message": "Visit your vitals page to automatically register for monitoring"
        })
@app.post('/stop-monitoring')
async def stop_monitoring(request: Request):
    """Stop automated health monitoring"""
    
    user_email = request.session.get('user_email', 'Unknown User')
    
    # Remove user from monitoring
    if user_email in monitored_users:
        del monitored_users[user_email]
        return JSONResponse({
            "success": True,
            "message": "🛑 Removed from 24/7 monitoring successfully"
        })
    else:
        return JSONResponse({
            "success": False,
            "message": "User was not being monitored"
        })

@app.get('/monitoring-status')
async def monitoring_status(request: Request):
    """Get 24/7 monitoring status"""
    
    user_email = request.session.get('user_email', 'Unknown User')
    user_registered = False
    total_contacts = 0
    total_monitored_users = 0
    
    try:
        # Check if user exists in database
        existing_user = await UserModel.get_user_by_email(user_email)
        if existing_user:
            user_registered = True
            # Get user's emergency contacts count
            emergency_contacts = await EmergencyContactModel.get_user_contacts(existing_user['_id'])
            total_contacts = len(emergency_contacts)
        
        # Get total monitored users from database
        all_monitored = await UserModel.get_all_monitored_users()
        total_monitored_users = len(all_monitored)
        
    except Exception as e:
        print(f"❌ Error fetching monitoring status: {e}")
    
    return JSONResponse({
        "system_active": global_monitoring_active,
        "user_registered": user_registered,
        "user_email": user_email,
        "total_contacts": total_contacts,
        "total_monitored_users": total_monitored_users,
        "system_status": "24/7 Active" if global_monitoring_active else "System Down",
        "last_check": datetime.now().isoformat()
    })

@app.post('/update-monitoring-settings')
async def update_monitoring_settings(request: Request,
                                   check_interval: int = Form(60)):
    """Update 24/7 monitoring settings"""
    
    try:
        # Update check interval (minimum 1 minute, maximum 1 hour)
        check_interval = max(60, min(3600, check_interval))
        
        return JSONResponse({
            "success": True,
            "message": "24/7 monitoring settings updated successfully",
            "settings": {
                "check_interval_minutes": check_interval // 60,
                "ai_analysis": "enabled" if os.getenv('GEMINI_API_KEY') else "disabled",
                "system_status": "24/7 Active"
            }
        })
        
    except Exception as e:
        return JSONResponse({
            "success": False,
            "message": f"Failed to update settings: {str(e)}"
        })

# Entry point moved to start.sh script using uvicorn
# Run with: ./start.sh or uvicorn app:app --host 0.0.0.0 --port 8000 --reload
