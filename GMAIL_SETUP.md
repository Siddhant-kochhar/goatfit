# 📧 Gmail Setup Guide for GoatFit Emergency Alerts

Follow these steps to configure Gmail SMTP for your emergency alert system:

## 🚀 Quick Setup (5 minutes)

### Step 1: Enable 2-Step Verification
1. Go to [Google Account Security](https://myaccount.google.com/security)
2. Under "Signing in to Google", click **2-Step Verification**
3. Follow the prompts to enable it (you'll need your phone)

### Step 2: Generate App Password
1. After enabling 2-Step Verification, go back to [Security](https://myaccount.google.com/security)
2. Click **App passwords** (you may need to sign in again)
3. Select **Mail** from the dropdown
4. Click **Generate**
5. **Copy the 16-digit password** (it looks like: `abcd efgh ijkl mnop`)

### Step 3: Configure GoatFit
1. Open `email_alert.py` in your editor
2. Replace this line:
   ```python
   GMAIL_ADDRESS = "your-gmail@gmail.com"
   ```
   With your actual Gmail:
   ```python
   GMAIL_ADDRESS = "youremail@gmail.com"
   ```

3. Replace this line:
   ```python
   GMAIL_APP_PASSWORD = "your-16-digit-app-password"
   ```
   With your App Password:
   ```python
   GMAIL_APP_PASSWORD = "abcd efgh ijkl mnop"
   ```

### Step 4: Test the System
```bash
python3 email_alert.py
```

## ✅ Success Indicators

If everything works, you'll see:
- ✅ Test email sent successfully
- Email arrives in your inbox within 1-2 minutes
- Professional emergency alert format

## ❌ Troubleshooting

### "Authentication Failed" Error
- ✅ Make sure you're using the **App Password**, not your Gmail password
- ✅ Check that 2-Step Verification is enabled
- ✅ Try generating a new App Password

### Email Not Arriving
- ✅ Check your Spam/Junk folder
- ✅ Verify Gmail address is spelled correctly
- ✅ Wait 2-3 minutes (Gmail SMTP can be slow)

### "Less Secure Apps" Message
- ❌ Don't enable "Less secure app access"
- ✅ Use App Passwords instead (more secure)

## 🔒 Security Notes

- **App Passwords are safer** than your regular Gmail password
- They work only for the specific app (GoatFit)
- You can revoke them anytime from Google Account settings
- Each app should have its own unique App Password

## 📧 Gmail Limits

- **Daily limit**: ~500 emails for personal Gmail accounts
- **Rate limit**: ~100 emails per hour
- **Perfect for**: Family emergency alerts (typically 1-5 emails)
- **Not for**: Mass marketing or high-volume sending

## 🧪 Testing Your Setup

Once configured, test with:

```python
# Test basic email
python3 email_alert.py

# Test emergency alert
python3 -c "
from email_alert import send_heart_rate_alert
send_heart_rate_alert('your@email.com', 'Test User', 185, 140)
"
```

---

**HadesFit Gmail Setup Complete! 🎉**

Your emergency alert system is now ready to protect your family's health and safety.
