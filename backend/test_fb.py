import firebase_admin
from firebase_admin import credentials, auth

dummy_cred = {
    "type": "service_account",
    "project_id": "spillthereel-caa31",
    "private_key_id": "dummy",
    "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC3\n-----END PRIVATE KEY-----\n",
    "client_email": "dummy@spillthereel-caa31.iam.gserviceaccount.com",
    "client_id": "123",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/dummy"
}

try:
    cred = credentials.Certificate(dummy_cred)
    app = firebase_admin.initialize_app(cred)
    print("Initialized OK")
    # To verify token verification doesn't crash on init:
    try:
        auth.verify_id_token("dummy_token_123")
    except Exception as e:
        print(f"Verify threw: {e}")
except Exception as e:
    print(f"Init threw: {e}")
