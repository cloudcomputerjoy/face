import os
import cv2
import numpy as np
from deepface import DeepFace
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, request
from datetime import datetime
import logging

# Standard logging for cloud monitoring
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# Firebase configuration using your Render Secret Path
cred_path = os.environ.get('FIREBASE_CREDENTIALS', '/etc/secrets/firebase-adminsdk.json')

try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    logging.info("✅ Firebase connected for Joy Saha's Enterprise System")
except Exception as e:
    logging.error(f"❌ Firebase Error: {e}")

# Global model setting
MODEL_NAME = "Facenet512"

@app.route('/register', methods=['POST'])
def register():
    try:
        name = request.form.get('name')
        user_id = request.form.get('id')
        step = request.form.get('step') # 1, 2, or 3
        
        file = request.files['image']
        img_array = np.frombuffer(file.read(), np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        # DeepFace detection and embedding generation
        objs = DeepFace.represent(img, model_name=MODEL_NAME, enforce_detection=True)
        embedding = objs[0]["embedding"]

        # Final step saves to Firestore
        if step == '3':
            db.collection('users').document(name).set({
                'name': name,
                'id': user_id,
                'encoding': embedding,
                'created_at': datetime.now()
            })
            return f"✅ Registration Complete: {name} (ID: {user_id})", 200
        
        return f"🔄 Shot {step}/3 captured", 200
    except Exception as e:
        logging.error(f"Reg Error: {e}")
        return "⚠️ Face not clear. Try again.", 200

@app.route('/verify', methods=['POST'])
def verify():
    try:
        file = request.files['image']
        img_array = np.frombuffer(file.read(), np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        # Extract current face embedding
        objs = DeepFace.represent(img, model_name=MODEL_NAME, enforce_detection=True)
        current_encoding = objs[0]["embedding"]

        # Fetch all users from Firestore
        users_ref = db.collection('users').stream()
        
        best_match = None
        # Threshold for Facenet512 (Cosine Distance: higher is better)
        threshold = 0.80 

        for doc in users_ref:
            user = doc.to_dict()
            known_encoding = user['encoding']
            
            # Fast vectorized math for 5s response time
            dist = np.dot(current_encoding, known_encoding) / (np.linalg.norm(current_encoding) * np.linalg.norm(known_encoding))
            
            if dist > threshold:
                best_match = user
                break

        if best_match:
            now = datetime.now()
            db.collection('attendance_logs').add({
                'name': best_match['name'],
                'id': best_match['id'],
                'timestamp': now,
                'status': 'Present'
            })
            return f"✅ Verified: {best_match['name']}\nID: {best_match['id']}", 200
        
        return "🚫 Unknown User", 200
    except Exception as e:
        return "⚠️ Recognition failed. Check lighting.", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)