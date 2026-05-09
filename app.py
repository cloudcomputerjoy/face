import os
import cv2
import uuid
import numpy as np
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, request
from datetime import datetime
from deepface import DeepFace
import logging

# -------------------------------
# LOGGING
# -------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

app = Flask(__name__)

# -------------------------------
# FIREBASE INIT
# -------------------------------
cred_path = os.environ.get(
    'FIREBASE_CREDENTIALS',
    'firebase-adminsdk.json'
)

if not firebase_admin._apps:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)

db = firestore.client()

logging.info("✅ Firebase Connected")

# -------------------------------
# TEMP IMAGE FOLDER
# -------------------------------
TEMP_DIR = "temp"
os.makedirs(TEMP_DIR, exist_ok=True)

registration_cache = {}

# -------------------------------
# SAVE IMAGE
# -------------------------------
def save_temp_image(file):
    filename = f"{uuid.uuid4()}.jpg"
    path = os.path.join(TEMP_DIR, filename)

    np_img = np.frombuffer(file.read(), np.uint8)
    img = cv2.imdecode(np_img, cv2.IMREAD_COLOR)

    cv2.imwrite(path, img)

    return path

# -------------------------------
# REGISTER
# -------------------------------
@app.route('/register', methods=['POST'])
def register():

    try:
        name = request.form.get('name')
        user_id = request.form.get('id')
        department = request.form.get('department')
        step = request.form.get('step')

        if 'image' not in request.files:
            return "❌ No Image", 400

        img_path = save_temp_image(request.files['image'])

        try:
            embedding = DeepFace.represent(
                img_path=img_path,
                model_name="ArcFace",
                enforce_detection=True
            )[0]["embedding"]

        except Exception:
            os.remove(img_path)
            return "⚠️ Face Not Detected", 200

        if step == '1':
            registration_cache[name] = []

        registration_cache[name].append(embedding)

        os.remove(img_path)

        # FINAL STEP
        if step == '3':

            avg_embedding = np.mean(
                registration_cache[name],
                axis=0
            )

            db.collection('users').document(name).set({
                'name': name,
                'id': user_id,
                'department': department,
                'embedding': avg_embedding.tolist(),
                'registered_at': datetime.now()
            })

            del registration_cache[name]

            logging.info(f"✅ Registered: {name}")

            return f"✅ {name} Registered Successfully"

        return f"📸 Step {step}/3 Captured"

    except Exception as e:
        logging.error(e)
        return "❌ Registration Failed", 500

# -------------------------------
# VERIFY
# -------------------------------
@app.route('/verify', methods=['POST'])
def verify():

    try:

        if 'image' not in request.files:
            return "❌ No Image", 400

        img_path = save_temp_image(request.files['image'])

        try:
            current_embedding = DeepFace.represent(
                img_path=img_path,
                model_name="ArcFace",
                enforce_detection=True
            )[0]["embedding"]

        except Exception:
            os.remove(img_path)
            return "⚠️ No Face Detected", 200

        users = db.collection('users').stream()

        best_match = None
        best_distance = 999

        for user in users:

            data = user.to_dict()

            stored_embedding = np.array(
                data['embedding']
            )

            distance = np.linalg.norm(
                np.array(current_embedding) - stored_embedding
            )

            if distance < best_distance:
                best_distance = distance
                best_match = data

        os.remove(img_path)

        THRESHOLD = 4

        if best_match and best_distance < THRESHOLD:

            now = datetime.now()

            db.collection('attendance_logs').add({
                'name': best_match['name'],
                'id': best_match['id'],
                'department': best_match['department'],
                'timestamp': now,
                'status': 'Present'
            })

            return (
                f"✅ Verified\n"
                f"Name: {best_match['name']}\n"
                f"ID: {best_match['id']}\n"
                f"Dept: {best_match['department']}\n"
                f"Time: {now.strftime('%H:%M:%S')}"
            )

        return "🚫 Face Not Recognized"

    except Exception as e:
        logging.error(e)
        return "❌ Verification Failed", 500

# -------------------------------
# HOME
# -------------------------------
@app.route('/')
def home():
    return "🚀 AI Attendance Server Running"

# -------------------------------
# MAIN
# -------------------------------
if __name__ == '__main__':

    port = int(os.environ.get('PORT', 10000))

    app.run(
        host='0.0.0.0',
        port=port
    )