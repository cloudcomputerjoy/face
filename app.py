import os
import cv2
import numpy as np
import face_recognition
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, request
from datetime import datetime
import logging

# --- 1. PRODUCTION LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# --- 2. FIREBASE INITIALIZATION ---
# This looks for the variable you added: /etc/secrets/firebase-adminsdk.json
cred_path = os.environ.get('FIREBASE_CREDENTIALS', 'firebase-adminsdk.json')

try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    logging.info("✅ Firebase connected successfully using: " + cred_path)
except Exception as e:
    logging.error(f"❌ Firebase Connection Failed: {e}")

# Cache to store the 3 images during registration
registration_cache = {}

# --- 3. DATABASE HELPER ---
def get_known_faces():
    """Fetch all registered users and their face encodings from Firestore."""
    users_ref = db.collection('users').stream()
    known_encodings = []
    known_data = [] 
    
    for doc in users_ref:
        data = doc.to_dict()
        if 'face_encoding' in data:
            known_encodings.append(np.array(data['face_encoding']))
            known_data.append(data)
            
    return known_encodings, known_data

# --- 4. REGISTRATION ENDPOINT (3-SHOT) ---
@app.route('/register', methods=['POST'])
def register_face():
    try:
        name = request.form.get('name')
        role = request.form.get('role')
        department = request.form.get('department')
        step = request.form.get('step') # '1', '2', or '3'
        
        if 'image' not in request.files:
            return "❌ No image received.", 400

        # Process image from memory
        file = request.files['image']
        np_img = np.frombuffer(file.read(), np.uint8)
        img = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
        rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # Detect face
        face_locations = face_recognition.face_locations(rgb_img)
        if not face_locations:
            return f"⚠️ Step {step} Failed: No face detected. Adjust lighting.", 200
            
        encoding = face_recognition.face_encodings(rgb_img, face_locations)[0]

        # Pipeline logic
        if step == '1':
            registration_cache[name] = []
            
        registration_cache[name].append(encoding)

        if step == '3':
            # Average the 3 encodings for 100% precision logic
            averaged_encoding = np.mean(registration_cache[name], axis=0)
            
            # Save to Firestore
            db.collection('users').document(name).set({
                'name': name,
                'role': role,
                'department': department,
                'face_encoding': averaged_encoding.tolist(),
                'registered_at': datetime.now()
            })
            
            if name in registration_cache:
                del registration_cache[name]
                
            logging.info(f"✅ Registered: {name} ({role})")
            return f"✅ Success! {name} is now registered in the cloud.", 200

        return f"🔄 Shot {step}/3 captured. Keep still...", 200

    except Exception as e:
        logging.error(f"Registration Error: {e}")
        return "❌ Server Error during registration.", 500

# --- 5. VERIFICATION ENDPOINT ---
@app.route('/verify', methods=['POST'])
def verify_face():
    try:
        if 'image' not in request.files:
            return "❌ No image received.", 400

        file = request.files['image']
        np_img = np.frombuffer(file.read(), np.uint8)
        img = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
        rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        face_locations = face_recognition.face_locations(rgb_img)
        if not face_locations:
            return "⚠️ No face detected. Try again.", 200

        face_encoding = face_recognition.face_encodings(rgb_img, face_locations)[0]
        
        # Load database
        known_encodings, known_data = get_known_faces()
        
        if not known_encodings:
            return "❌ Database is empty. Register someone first.", 200

        # High Accuracy Comparison
        # Retrieve strictness from Env Var or default to 0.45
        tolerance = float(os.environ.get('STRICTNESS_TOLERANCE', 0.45))
        face_distances = face_recognition.face_distance(known_encodings, face_encoding)
        best_match_index = np.argmin(face_distances)
        
        if face_distances[best_match_index] <= tolerance:
            user = known_data[best_match_index]
            
            # Log Attendance
            now = datetime.now()
            db.collection('attendance_logs').add({
                'name': user['name'],
                'role': user['role'],
                'department': user['department'],
                'timestamp': now,
                'status': 'Present'
            })
            
            return f"✅ Verified: {user['name']}\nDept: {user['department']}\nLogged at {now.strftime('%H:%M')}", 200
            
        return "🚫 Access Denied. Face not recognized.", 200

    except Exception as e:
        logging.error(f"Verification Error: {e}")
        return "❌ Internal Server Error.", 500

if __name__ == '__main__':
    # Use environment port for Render compatibility
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)