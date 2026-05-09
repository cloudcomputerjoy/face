import os
import cv2
import numpy as np
import face_recognition
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, request
from datetime import datetime
import logging

# Production Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# --- ENTERPRISE FIREBASE CONNECTION ---
# In production, Render injects the path to the secure credential file
cred_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 'firebase-adminsdk.json')

try:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    logging.info("✅ Firebase connected securely.")
except Exception as e:
    logging.critical(f"❌ FATAL: Firebase Connection Failed: {e}")

registration_cache = {}

def get_known_faces():
    users_ref = db.collection('users').stream()
    known_encodings = []
    known_data = [] 
    for doc in users_ref:
        data = doc.to_dict()
        if 'face_encoding' in data:
            known_encodings.append(np.array(data['face_encoding']))
            known_data.append(data)
    return known_encodings, known_data

@app.route('/register', methods=['POST'])
def register_face():
    try:
        name = request.form.get('name')
        role = request.form.get('role')
        department = request.form.get('department')
        step = request.form.get('step')
        
        if 'image' not in request.files: return "❌ No image received.", 400

        file = request.files['image']
        np_img = np.frombuffer(file.read(), np.uint8)
        img = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
        rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        face_locations = face_recognition.face_locations(rgb_img)
        if not face_locations: return f"⚠️ Step {step} Failed: No face detected.", 200
            
        encoding = face_recognition.face_encodings(rgb_img, face_locations)[0]

        if step == '1': registration_cache[name] = [] 
        registration_cache[name].append(encoding)

        if step == '3':
            averaged_encoding = np.mean(registration_cache[name], axis=0)
            db.collection('users').document(name).set({
                'name': name,
                'role': role,
                'department': department,
                'face_encoding': averaged_encoding.tolist(), 
                'registered_at': datetime.now()
            })
            del registration_cache[name]
            return f"✅ Registration Complete for {name}!", 200

        return f"🔄 Step {step}/3 captured.", 200

    except Exception as e:
        logging.error(f"Registration error: {e}")
        return "❌ Internal Server Error.", 500

@app.route('/verify', methods=['POST'])
def verify_face():
    try:
        if 'image' not in request.files: return "❌ No image received.", 400

        file = request.files['image']
        np_img = np.frombuffer(file.read(), np.uint8)
        img = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
        rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        face_locations = face_recognition.face_locations(rgb_img)
        if not face_locations: return "⚠️ No face detected.", 200

        face_encoding = face_recognition.face_encodings(rgb_img, face_locations)[0]
        known_encodings, known_data = get_known_faces()
        
        if not known_encodings: return "❌ Database empty. Register users first.", 200

        face_distances = face_recognition.face_distance(known_encodings, face_encoding)
        best_match_index = np.argmin(face_distances)
        
        if face_distances[best_match_index] <= 0.45:
            user = known_data[best_match_index]
            now = datetime.now()
            
            # Log to Firestore
            db.collection('attendance_logs').document().set({
                'name': user['name'],
                'role': user['role'],
                'department': user['department'],
                'timestamp': now,
                'status': 'Present'
            })
            
            time_str = now.strftime("%I:%M %p")
            return f"✅ Verified: {user['name']}\nLogged at {time_str}", 200
            
        return "🚫 Face not recognized.", 200

    except Exception as e:
        logging.error(f"Verification error: {e}")
        return "❌ Internal Server Error.", 500

# Gunicorn handles the execution in production, this is only for local testing
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)