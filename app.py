import os
import cv2
import time
import numpy as np
import logging
from typing import Dict, Any, List, Tuple
from functools import wraps

from deepface import DeepFace
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename

# ==========================================
# 1. CORE CONFIGURATION & SECURITY
# ==========================================
class Config:
    MODEL_NAME = "Facenet512"
    SIMILARITY_THRESHOLD = float(os.environ.get('STRICTNESS_THRESHOLD', 0.82))
    CACHE_TTL_SECONDS = 300
    # Security: Require an API key to talk to this server
    API_KEY = os.environ.get('API_KEY', 'AAU_ENTERPRISE_SECRET_2026') 

app = Flask(__name__)
CORS(app) # Enables secure cross-origin requests

# Structured Enterprise Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-8s | %(module)s | %(message)s')
logger = logging.getLogger("AAU_Biometrics")

# ==========================================
# 2. CUSTOM EXCEPTIONS
# ==========================================
class BiometricError(Exception):
    """Base exception for biometric processing failures."""
    pass

class ImageCorruptionError(BiometricError): pass
class FaceNotFoundError(BiometricError): pass
class MultipleFacesError(BiometricError): pass

# ==========================================
# 3. DATABASE CONNECTION
# ==========================================
def initialize_firestore() -> firestore.client:
    try:
        cred_path = os.environ.get('FIREBASE_CREDENTIALS', '/etc/secrets/firebase-adminsdk.json')
        if not firebase_admin._apps:
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        logger.info("✅ Secure connection to Firestore established.")
        return firestore.client()
    except Exception as e:
        logger.critical(f"❌ Database connection failed: {e}")
        return None

db = initialize_firestore()
registration_cache: Dict[str, Dict[str, Any]] = {}

# ==========================================
# 4. MIDDLEWARE & HELPERS
# ==========================================
def require_api_key(f):
    """Decorator to enforce API Key authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        provided_key = request.headers.get('x-api-key')
        if provided_key != Config.API_KEY:
            logger.warning(f"Unauthorized access attempt from {request.remote_addr}")
            # 🛑 THIS WAS THE FIX: Return clean JSON instead of an HTML abort page
            return jsonify({"status": "error", "message": "Unauthorized: Invalid or missing API Key"}), 401
        return f(*args, **kwargs)
    return decorated_function

def manage_memory():
    """Garbage collector for abandoned registrations."""
    now = time.time()
    stale_keys = [k for k, v in registration_cache.items() if (now - v['timestamp']) > Config.CACHE_TTL_SECONDS]
    for k in stale_keys:
        del registration_cache[k]
        logger.debug(f"Cleared stale cache for session: {k}")

def extract_embedding(image_bytes: bytes) -> List[float]:
    """Decodes image and extracts biometric embedding with strict validation."""
    np_img = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
    
    if img is None:
        raise ImageCorruptionError("Image data could not be decoded.")

    try:
        objs = DeepFace.represent(img, model_name=Config.MODEL_NAME, enforce_detection=True)
    except ValueError:
        raise FaceNotFoundError("No face detected in the frame.")

    if len(objs) > 1:
        raise MultipleFacesError(f"Multiple faces detected ({len(objs)}). Frame must contain exactly one face.")

    return objs[0]["embedding"]

# ==========================================
# 5. API ROUTES
# ==========================================
@app.route('/health', methods=['GET'])
def health_check() -> Tuple[Any, int]:
    return jsonify({"status": "healthy", "service": "AAU Biometrics API", "timestamp": time.time()}), 200

@app.route('/register', methods=['POST'])
@require_api_key
def register_user() -> Tuple[Any, int]:
    try:
        manage_memory()
        
        # Sanitize Inputs
        name = request.form.get('name', '').strip()
        user_id = secure_filename(request.form.get('id', '').strip()) # Prevents injection
        step = request.form.get('step')
        
        if not name or not user_id or 'image' not in request.files:
            return jsonify({"status": "error", "message": "Malformed request geometry."}), 400

        try:
            embedding = extract_embedding(request.files['image'].read())
        except BiometricError as e:
            return jsonify({"status": "error", "message": str(e)}), 422 # 422 Unprocessable Entity

        # 3-Shot Aggregation Pipeline
        if step == '1' or user_id not in registration_cache:
            registration_cache[user_id] = {'encodings': [embedding], 'timestamp': time.time()}
        else:
            registration_cache[user_id]['encodings'].append(embedding)
            registration_cache[user_id]['timestamp'] = time.time()

        # Finalize and Save
        if step == '3':
            avg_embedding = np.mean(registration_cache[user_id]['encodings'], axis=0).tolist()
            db.collection('users').document(user_id).set({
                'name': name,
                'id': user_id,
                'department': request.form.get('department', 'N/A').strip(),
                'encoding': avg_embedding,
                'created_at': firestore.SERVER_TIMESTAMP
            })
            del registration_cache[user_id]
            logger.info(f"✅ Identity Secured: {name} [{user_id}]")
            return jsonify({"status": "success", "message": f"{name} successfully registered."}), 201

        return jsonify({"status": "progress", "message": f"Biometric frame {step}/3 processed."}), 202

    except Exception as e:
        logger.error(f"Registration fault: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal processing fault."}), 500

@app.route('/verify', methods=['POST'])
@require_api_key
def verify_user() -> Tuple[Any, int]:
    try:
        if 'image' not in request.files:
            return jsonify({"status": "error", "message": "Payload missing image buffer."}), 400

        try:
            curr_enc = extract_embedding(request.files['image'].read())
        except BiometricError as e:
            return jsonify({"status": "error", "message": str(e)}), 422

        # High-Speed Vector Matcher
        users_ref = db.collection('users').stream()
        best_match, highest_score = None, 0.0

        for doc in users_ref:
            u_data = doc.to_dict()
            known_enc = u_data.get('encoding')
            if not known_enc: continue
            
            # Mathematical Cosine Distance
            score = np.dot(curr_enc, known_enc) / (np.linalg.norm(curr_enc) * np.linalg.norm(known_enc))
            if score > highest_score:
                highest_score = score
                if score >= Config.SIMILARITY_THRESHOLD:
                    best_match = u_data

        if best_match:
            db.collection('attendance_logs').add({
                'name': best_match['name'],
                'id': best_match['id'],
                'timestamp': firestore.SERVER_TIMESTAMP,
                'status': 'Present',
                'confidence': round(highest_score * 100, 2)
            })
            logger.info(f"🔓 Access Granted: {best_match['id']} (Confidence: {highest_score:.4f})")
            return jsonify({"status": "success", "user": best_match['name'], "id": best_match['id']}), 200
        
        logger.warning(f"🔒 Access Denied. Highest match confidence: {highest_score:.4f}")
        return jsonify({"status": "failed", "message": "Identity not recognized."}), 403

    except Exception as e:
        logger.error(f"Verification fault: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal processing fault."}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)