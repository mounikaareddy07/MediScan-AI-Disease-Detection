"""
MediScan AI - Flask Backend Application
Main API server with endpoints for authentication, scan analysis, and AI assistant.
"""

import os
import json
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS
from werkzeug.utils import secure_filename

# Import local modules
from database.db import get_db, init_db
from utils.auth import hash_password, verify_password, generate_token, validate_signup
from models.ai_model import predict, get_available_models
from utils.heatmap import generate_heatmap

# ─── App Configuration ───────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'mediscan-ai-secret-key-2024')
CORS(app, supports_credentials=True)

# Folder configuration
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
HEATMAP_FOLDER = os.path.join(os.path.dirname(__file__), 'heatmaps')
FRONTEND_FOLDER = os.path.join(os.path.dirname(__file__), '..', 'frontend')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(HEATMAP_FOLDER, exist_ok=True)

# In-memory session store (token → user_id)
active_sessions = {}


def allowed_file(filename):
    """Check if the uploaded file has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ─── Authentication Endpoints ────────────────────────────────────────

@app.route('/api/signup', methods=['POST'])
def signup():
    """Register a new user account."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    full_name = data.get('full_name', '').strip()
    username = data.get('username', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    confirm_password = data.get('confirm_password', '')

    # Validate input fields
    errors = validate_signup(full_name, username, email, password, confirm_password)
    if errors:
        return jsonify({'success': False, 'message': errors[0], 'errors': errors}), 400

    # Check if user already exists
    db = get_db()
    existing = db.execute(
        'SELECT id FROM users WHERE email = ? OR username = ?', (email, username)
    ).fetchone()

    if existing:
        db.close()
        return jsonify({'success': False, 'message': 'Email or username already registered'}), 409

    # Create user
    pwd_hash = hash_password(password)
    db.execute(
        'INSERT INTO users (full_name, username, email, password_hash) VALUES (?, ?, ?, ?)',
        (full_name, username, email, pwd_hash)
    )
    db.commit()
    db.close()

    return jsonify({'success': True, 'message': 'Account created successfully! Please login.'}), 201


@app.route('/api/login', methods=['POST'])
def login():
    """Authenticate user and return session token."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    identifier = data.get('identifier', '').strip()  # Can be email or username
    password = data.get('password', '')
    remember = data.get('remember', False)

    if not identifier or not password:
        return jsonify({'success': False, 'message': 'Please fill in all fields'}), 400

    # Find user by email or username
    db = get_db()
    user = db.execute(
        'SELECT * FROM users WHERE email = ? OR username = ?',
        (identifier.lower(), identifier)
    ).fetchone()
    db.close()

    if not user or not verify_password(password, user['password_hash']):
        return jsonify({'success': False, 'message': 'Invalid credentials. Please try again.'}), 401

    # Generate session token
    token = generate_token()
    active_sessions[token] = {
        'user_id': user['id'],
        'username': user['username'],
        'full_name': user['full_name'],
        'email': user['email']
    }

    return jsonify({
        'success': True,
        'message': 'Login successful!',
        'token': token,
        'user': {
            'id': user['id'],
            'username': user['username'],
            'full_name': user['full_name'],
            'email': user['email']
        }
    })


@app.route('/api/logout', methods=['POST'])
def logout():
    """Invalidate user session."""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if token in active_sessions:
        del active_sessions[token]
    return jsonify({'success': True, 'message': 'Logged out successfully'})


def get_current_user():
    """Get the current authenticated user from the session token."""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    return active_sessions.get(token)


# ─── Scan Analysis Endpoints ─────────────────────────────────────────

@app.route('/api/models', methods=['GET'])
def list_models():
    """Return available AI models and their status."""
    return jsonify({'success': True, 'models': get_available_models()})


@app.route('/api/analyze', methods=['POST'])
def analyze_scan():
    """Upload and analyze a medical scan image."""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401

    if 'scan' not in request.files:
        return jsonify({'success': False, 'message': 'No scan file uploaded'}), 400

    file = request.files['scan']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({'success': False, 'message': 'Invalid file type. Please upload PNG, JPG, or JPEG'}), 400

    # Get scan type from form data (default: chest_xray)
    scan_type = request.form.get('scan_type', 'chest_xray')

    # Save uploaded file
    original_filename = secure_filename(file.filename)
    unique_filename = f"{uuid.uuid4().hex}_{original_filename}"
    file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
    file.save(file_path)

    # Run AI prediction with scan type
    result = predict(file_path, scan_type=scan_type)

    if not result['success']:
        return jsonify({'success': False, 'message': 'Analysis failed. Please try again.'}), 500

    # Generate heatmap
    heatmap_filename = f"heatmap_{unique_filename}"
    heatmap_path = os.path.join(HEATMAP_FOLDER, heatmap_filename)
    generate_heatmap(file_path, result['prediction'], heatmap_path, scan_type=scan_type)

    # Save scan record to database
    db = get_db()
    cursor = db.execute(
        '''INSERT INTO scans 
           (user_id, filename, original_filename, prediction, risk_score, confidence, insights, heatmap_filename) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (user['user_id'], unique_filename, original_filename,
         result['prediction'], result['risk_score'], result['confidence'],
         json.dumps(result['insights']), heatmap_filename)
    )
    scan_id = cursor.lastrowid
    db.commit()
    db.close()

    return jsonify({
        'success': True,
        'scan_id': scan_id,
        'prediction': result['prediction'],
        'risk_score': result['risk_score'],
        'confidence': result['confidence'],
        'insights': result['insights'],
        'probabilities': result['probabilities'],
        'scan_type': scan_type,
        'scan_type_display': result.get('scan_type_display', scan_type),
        'real_model': result.get('real_model', False),
        'scan_url': f'/uploads/{unique_filename}',
        'heatmap_url': f'/heatmaps/{heatmap_filename}'
    })


@app.route('/api/history', methods=['GET'])
def get_scan_history():
    """Get scan history for the current user."""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401

    db = get_db()
    scans = db.execute(
        'SELECT * FROM scans WHERE user_id = ? ORDER BY created_at DESC',
        (user['user_id'],)
    ).fetchall()
    db.close()

    history = []
    for scan in scans:
        history.append({
            'id': scan['id'],
            'filename': scan['original_filename'],
            'prediction': scan['prediction'],
            'risk_score': scan['risk_score'],
            'confidence': scan['confidence'],
            'insights': json.loads(scan['insights']) if scan['insights'] else [],
            'scan_url': f'/uploads/{scan["filename"]}',
            'heatmap_url': f'/heatmaps/{scan["heatmap_filename"]}' if scan['heatmap_filename'] else None,
            'date': scan['created_at']
        })

    return jsonify({'success': True, 'history': history})


@app.route('/api/scan/<int:scan_id>', methods=['GET'])
def get_scan_detail(scan_id):
    """Get detailed information about a specific scan."""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401

    db = get_db()
    scan = db.execute(
        'SELECT * FROM scans WHERE id = ? AND user_id = ?',
        (scan_id, user['user_id'])
    ).fetchone()
    db.close()

    if not scan:
        return jsonify({'success': False, 'message': 'Scan not found'}), 404

    return jsonify({
        'success': True,
        'scan': {
            'id': scan['id'],
            'filename': scan['original_filename'],
            'prediction': scan['prediction'],
            'risk_score': scan['risk_score'],
            'confidence': scan['confidence'],
            'insights': json.loads(scan['insights']) if scan['insights'] else [],
            'scan_url': f'/uploads/{scan["filename"]}',
            'heatmap_url': f'/heatmaps/{scan["heatmap_filename"]}' if scan['heatmap_filename'] else None,
            'date': scan['created_at']
        }
    })


# ─── AI Assistant Endpoint ───────────────────────────────────────────

@app.route('/api/assistant', methods=['POST'])
def ai_assistant():
    """AI assistant that helps users understand their scan results."""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': 'Authentication required'}), 401

    data = request.get_json()
    message = data.get('message', '').strip().lower()
    scan_context = data.get('scan_context', None)

    if not message:
        return jsonify({'success': False, 'message': 'Please enter a message'}), 400

    # Generate intelligent response based on context and query
    response = generate_assistant_response(message, scan_context, user['full_name'])

    return jsonify({'success': True, 'response': response})


# ─── Medical Knowledge Base ─────────────────────────────────────────

DISEASE_KNOWLEDGE = {
    # ── Chest X-ray diseases ──
    'PNEUMONIA': {
        'name': 'Pneumonia',
        'icon': '🫁',
        'scan_type': 'Chest X-ray',
        'description': 'Pneumonia is an infection that inflames the air sacs in one or both lungs. The air sacs may fill with fluid or pus.',
        'symptoms': [
            'Cough with phlegm or pus',
            'Fever, sweating, and chills',
            'Shortness of breath',
            'Chest pain when breathing or coughing',
            'Fatigue and loss of appetite',
            'Nausea, vomiting, or diarrhea'
        ],
        'findings': [
            'Lung opacity detected in lower lobe regions',
            'Consolidation patterns consistent with bacterial pneumonia',
            'Air bronchograms may be present within opacified region',
            'Possible inflammation in alveolar spaces'
        ],
        'treatment': 'Antibiotics (bacterial), antiviral medications (viral), rest, fluids, and oxygen therapy if severe.',
        'prevention': 'Vaccination (PCV13, PPSV23), good hand hygiene, avoiding smoking, maintaining strong immune system.',
        'urgency': 'moderate',
        'specialist': 'pulmonologist'
    },
    'NORMAL': {
        'name': 'Normal (Healthy)',
        'icon': '✅',
        'scan_type': 'Chest X-ray',
        'description': 'No significant abnormalities detected. The scan appears healthy.',
        'findings': [
            'Lung fields appear clear bilaterally',
            'Heart size and mediastinal contours within normal limits',
            'Costophrenic angles are clear',
            'No pleural effusion or pneumothorax identified'
        ],
        'urgency': 'none'
    },

    # ── Brain Tumor diseases ──
    'glioma': {
        'name': 'Glioma',
        'icon': '🧠',
        'scan_type': 'Brain MRI',
        'description': 'Gliomas are tumors that arise from glial cells in the brain. They are the most common type of primary brain tumor and can range from low-grade (slow growing) to high-grade (aggressive).',
        'symptoms': [
            'Persistent headaches that worsen over time',
            'Seizures (new onset)',
            'Cognitive changes or personality shifts',
            'Nausea and vomiting',
            'Vision problems or speech difficulties',
            'Weakness on one side of the body'
        ],
        'findings': [
            'Irregular mass with infiltrative growth pattern',
            'Contrast enhancement suggesting higher-grade lesion',
            'Surrounding edema (brain swelling) detected',
            'Possible mass effect on adjacent structures'
        ],
        'treatment': 'Surgery (tumor resection), radiation therapy, chemotherapy (temozolomide), targeted therapy.',
        'prevention': 'No known prevention. Regular neurological check-ups if family history of brain tumors.',
        'urgency': 'high',
        'specialist': 'neurosurgeon and neuro-oncologist'
    },
    'meningioma': {
        'name': 'Meningioma',
        'icon': '🧠',
        'scan_type': 'Brain MRI',
        'description': 'Meningiomas arise from the meninges (membranes surrounding the brain). Most are benign (non-cancerous) and slow-growing, but they can cause symptoms by pressing on the brain.',
        'symptoms': [
            'Gradual onset headaches',
            'Vision changes (blurred or double vision)',
            'Hearing loss or ringing in ears',
            'Memory difficulties',
            'Seizures',
            'Weakness in arms or legs'
        ],
        'findings': [
            'Well-defined extra-axial mass with dural attachment',
            'Homogeneous enhancement pattern',
            'Dural tail sign present',
            'Mass effect on adjacent brain structures'
        ],
        'treatment': 'Observation (small/asymptomatic), surgical removal, stereotactic radiosurgery for residual or recurrent tumors.',
        'prevention': 'No known prevention. Avoid unnecessary radiation exposure.',
        'urgency': 'moderate',
        'specialist': 'neurosurgeon'
    },
    'pituitary': {
        'name': 'Pituitary Tumor',
        'icon': '🧠',
        'scan_type': 'Brain MRI',
        'description': 'Pituitary tumors (adenomas) develop in the pituitary gland at the base of the brain. Most are benign and can affect hormone production.',
        'symptoms': [
            'Vision problems (especially peripheral vision loss)',
            'Unexplained weight changes',
            'Fatigue and weakness',
            'Hormonal imbalances (irregular periods, infertility)',
            'Headaches',
            'Excessive thirst or urination'
        ],
        'findings': [
            'Sellar/parasellar mass consistent with pituitary adenoma',
            'Pituitary gland appears enlarged',
            'Possible optic chiasm compression',
            'Cavernous sinus involvement evaluation needed'
        ],
        'treatment': 'Medication (dopamine agonists), transsphenoidal surgery, radiation therapy, hormone replacement.',
        'prevention': 'No known prevention. Regular hormonal screening if family history.',
        'urgency': 'moderate',
        'specialist': 'endocrinologist and neurosurgeon'
    },
    'notumor': {
        'name': 'No Tumor Detected',
        'icon': '✅',
        'scan_type': 'Brain MRI',
        'description': 'No tumors or mass lesions detected in the brain. Brain structures appear normal.',
        'findings': [
            'Brain parenchyma appears normal',
            'Ventricular system symmetrical and normal in size',
            'No midline shift or mass effect',
            'No abnormal enhancement patterns'
        ],
        'urgency': 'none'
    },

    # ── Skin Lesion diseases ──
    'malignant': {
        'name': 'Malignant Lesion (Suspected Melanoma)',
        'icon': '🔬',
        'scan_type': 'Skin Lesion',
        'description': 'The lesion shows features concerning for malignancy. Melanoma is the most serious type of skin cancer, developing from melanocytes (pigment cells). Early detection is critical for survival.',
        'symptoms': [
            'Asymmetric mole or spot (ABCDE rule)',
            'Irregular or blurred borders',
            'Multiple colors (brown, black, red, white, blue)',
            'Diameter larger than 6mm (pencil eraser)',
            'Evolving size, shape, or color',
            'Itching, bleeding, or crusting'
        ],
        'findings': [
            '⚠️ Lesion shows features concerning for malignancy',
            'Irregular borders and asymmetric shape detected',
            'Color variation and uneven pigmentation',
            'Dermatoscopic pattern analysis suggests further evaluation'
        ],
        'treatment': 'Surgical excision with margins, sentinel lymph node biopsy, immunotherapy, targeted therapy, or radiation.',
        'prevention': 'Use sunscreen (SPF 30+), avoid tanning beds, wear protective clothing, regular skin self-exams, annual dermatologist visits.',
        'urgency': 'high',
        'specialist': 'dermatologist and oncologist'
    },
    'benign': {
        'name': 'Benign Lesion',
        'icon': '✅',
        'scan_type': 'Skin Lesion',
        'description': 'The skin lesion appears to have benign (non-cancerous) characteristics. Common benign lesions include moles (nevi), seborrheic keratoses, and dermatofibromas.',
        'findings': [
            'Lesion shows regular, symmetric features',
            'Uniform color distribution observed',
            'Smooth, well-defined borders',
            'Dermatoscopic patterns consistent with benign lesion'
        ],
        'urgency': 'low'
    },

    # ── Retinal diseases ──
    'CNV': {
        'name': 'Choroidal Neovascularization (CNV)',
        'icon': '👁️',
        'scan_type': 'Retinal OCT',
        'description': 'CNV involves the growth of new, abnormal blood vessels beneath the retina. It is commonly associated with wet age-related macular degeneration (AMD) and can lead to rapid vision loss.',
        'symptoms': [
            'Sudden or gradual central vision loss',
            'Distorted vision (straight lines appear wavy)',
            'Dark or blind spots in central vision',
            'Colors appear less vivid',
            'Difficulty reading or recognizing faces'
        ],
        'findings': [
            'Abnormal blood vessel growth beneath the retina',
            'Subretinal fluid accumulation detected',
            'Retinal thickening in macular region',
            'Features consistent with wet AMD'
        ],
        'treatment': 'Anti-VEGF injections (ranibizumab, aflibercept, bevacizumab), photodynamic therapy, laser photocoagulation.',
        'prevention': 'Regular eye exams after age 50, healthy diet rich in leafy greens, avoid smoking, manage cardiovascular risk factors.',
        'urgency': 'high',
        'specialist': 'retinal specialist / ophthalmologist'
    },
    'DME': {
        'name': 'Diabetic Macular Edema (DME)',
        'icon': '👁️',
        'scan_type': 'Retinal OCT',
        'description': 'DME is a complication of diabetic retinopathy where fluid leaks into the macula (center of the retina), causing swelling and vision problems.',
        'symptoms': [
            'Blurry or wavy central vision',
            'Colors appear washed out or faded',
            'Difficulty reading fine print',
            'Dark or empty areas in vision',
            'Vision changes that fluctuate during the day'
        ],
        'findings': [
            'Macular thickening due to fluid accumulation',
            'Cystoid macular changes observed',
            'Hard exudates near the fovea',
            'Retinal layer disruption detected'
        ],
        'treatment': 'Anti-VEGF injections, corticosteroid implants, focal/grid laser therapy, tight blood sugar control.',
        'prevention': 'Control blood sugar (HbA1c < 7%), manage blood pressure and cholesterol, annual dilated eye exams for diabetics.',
        'urgency': 'high',
        'specialist': 'retinal specialist / ophthalmologist'
    },
    'DRUSEN': {
        'name': 'Drusen (Early AMD)',
        'icon': '👁️',
        'scan_type': 'Retinal OCT',
        'description': 'Drusen are yellow-white deposits that accumulate under the retina. They are an early sign of age-related macular degeneration (AMD). Small drusen are common with aging, but large drusen increase AMD risk.',
        'symptoms': [
            'Usually no symptoms in early stages',
            'Mild blurriness in central vision',
            'Need for brighter light when reading',
            'Difficulty adapting to low light',
            'Gradual color perception changes'
        ],
        'findings': [
            'Yellow-white deposits beneath the retina',
            'Drusen visible in macular region',
            'RPE (retinal pigment epithelium) changes',
            'Early signs of age-related macular degeneration'
        ],
        'treatment': 'AREDS2 supplements (vitamins C, E, zinc, copper, lutein, zeaxanthin), lifestyle modifications, monitoring.',
        'prevention': 'Anti-oxidant rich diet, regular exercise, avoid smoking, UV-protective sunglasses, annual eye exams after 50.',
        'urgency': 'moderate',
        'specialist': 'ophthalmologist'
    },

    # ── Bone Fracture ──
    'fractured': {
        'name': 'Bone Fracture',
        'icon': '🦴',
        'scan_type': 'Bone X-ray',
        'description': 'A fracture is a break in the continuity of bone. Fractures can range from hairline cracks to complete breaks, and severity depends on location, type, and displacement.',
        'symptoms': [
            'Sudden, severe pain at the injury site',
            'Swelling, bruising, and tenderness',
            'Inability to bear weight or use the limb',
            'Visible deformity or unnatural angle',
            'Numbness or tingling below the injury',
            'Grinding sensation during movement'
        ],
        'findings': [
            '⚠️ Fracture line detected in bone cortex',
            'Discontinuity in bone structure identified',
            'Possible displacement or angulation',
            'Surrounding soft tissue swelling'
        ],
        'treatment': 'Immobilization (cast/splint), pain management, surgical fixation (plates/screws/rods) if displaced, physical therapy for rehabilitation.',
        'prevention': 'Calcium and Vitamin D supplementation, weight-bearing exercise, fall prevention, protective gear during sports.',
        'urgency': 'high',
        'specialist': 'orthopedic surgeon'
    },
    'not fractured': {
        'name': 'No Fracture Detected',
        'icon': '✅',
        'scan_type': 'Bone X-ray',
        'description': 'No fracture lines or breaks detected in the bone X-ray. Bone cortex appears intact and continuous.',
        'findings': [
            'Bone cortex appears intact and continuous',
            'Joint spaces within normal limits',
            'No signs of dislocation or subluxation',
            'Normal bone density for demographics'
        ],
        'urgency': 'none'
    }
}

# Scan type descriptions for general queries
SCAN_TYPE_INFO = {
    'chest_xray': {
        'name': 'Chest X-ray Analysis',
        'icon': '🫁',
        'detects': ['Normal', 'Pneumonia'],
        'description': 'Analyzes chest X-ray images to detect pneumonia and other lung abnormalities using MobileNetV2 CNN.',
        'accuracy': '~92-95%'
    },
    'brain_tumor': {
        'name': 'Brain Tumor MRI Analysis',
        'icon': '🧠',
        'detects': ['Glioma', 'Meningioma', 'Pituitary Tumor', 'No Tumor'],
        'description': 'Classifies brain MRI scans into 4 categories to identify and differentiate brain tumors.',
        'accuracy': '~90-94%'
    },
    'skin_lesion': {
        'name': 'Skin Lesion Analysis',
        'icon': '🔬',
        'detects': ['Benign', 'Malignant (Melanoma)'],
        'description': 'Analyzes dermoscopic skin images to detect potentially malignant lesions and melanoma.',
        'accuracy': '~88-92%'
    },
    'retinal': {
        'name': 'Retinal OCT Analysis',
        'icon': '👁️',
        'detects': ['CNV', 'DME', 'Drusen', 'Normal'],
        'description': 'Detects retinal diseases from OCT scans including macular degeneration and diabetic eye disease.',
        'accuracy': '~93-96%'
    },
    'bone_fracture': {
        'name': 'Bone Fracture X-ray Analysis',
        'icon': '🦴',
        'detects': ['Fractured', 'Not Fractured'],
        'description': 'Detects bone fractures from X-ray images across multiple body regions.',
        'accuracy': '~85-90%'
    }
}


def generate_assistant_response(message, scan_context, user_name):
    """Generate an intelligent AI assistant response based on all 5 scan type models."""

    # ── Greetings ──
    if any(word in message for word in ['hello', 'hi', 'hey', 'greetings', 'good morning', 'good evening']):
        return (f"Hello {user_name}! 👋 I'm MediScan AI Assistant, trained on **5 medical imaging models**.\n\n"
                f"I can help you with:\n"
                f"🫁 **Chest X-rays** — Pneumonia detection\n"
                f"🧠 **Brain MRI** — Tumor classification\n"
                f"🔬 **Skin Lesions** — Melanoma screening\n"
                f"👁️ **Retinal OCT** — Eye disease detection\n"
                f"🦴 **Bone X-rays** — Fracture detection\n\n"
                f"Upload a scan or ask me anything about these conditions!")

    # ── Scan Result Explanation (Context-Aware) ──
    if any(word in message for word in ['explain', 'result', 'report', 'analysis', 'diagnosis', 'mean', 'finding']):
        if scan_context:
            return _explain_scan_result(scan_context)
        return ("I'd be happy to explain your scan results! Please upload a scan first using the **Scan** page, then ask me to explain.\n\n"
                "I can analyze results from all 5 scan types:\n"
                "🫁 Chest X-ray • 🧠 Brain MRI • 🔬 Skin Lesion • 👁️ Retinal OCT • 🦴 Bone X-ray")

    # ── Specific Disease Queries ──

    # Brain tumor keywords
    if any(word in message for word in ['glioma']):
        return _disease_info('glioma')
    if any(word in message for word in ['meningioma']):
        return _disease_info('meningioma')
    if any(word in message for word in ['pituitary']):
        return _disease_info('pituitary')
    if any(word in message for word in ['brain tumor', 'brain cancer', 'brain tumour']):
        return _brain_tumor_overview()

    # Chest diseases
    if 'pneumonia' in message:
        return _disease_info('PNEUMONIA')
    if any(word in message for word in ['tuberculosis', 'tb ']):
        return _tb_info()

    # Skin conditions
    if any(word in message for word in ['melanoma', 'skin cancer', 'malignant', 'lesion', 'mole']):
        return _disease_info('malignant')

    # Eye conditions
    if any(word in message for word in ['retinal', 'retina', 'eye', 'macular', 'amd']):
        return _retinal_overview()
    if 'cnv' in message or 'neovascularization' in message:
        return _disease_info('CNV')
    if 'dme' in message or 'diabetic macular' in message:
        return _disease_info('DME')
    if 'drusen' in message:
        return _disease_info('DRUSEN')

    # Bone conditions
    if any(word in message for word in ['fracture', 'broken bone', 'bone break', 'crack']):
        return _disease_info('fractured')

    # ── Scan Type Queries ──
    if any(word in message for word in ['scan type', 'what scan', 'which scan', 'types', 'supported', 'models']):
        return _scan_types_overview()

    # ── Risk & Precautions (scan-type aware) ──
    if any(word in message for word in ['risk', 'precaution', 'prevent', 'safety', 'protect', 'avoid']):
        if scan_context:
            return _precautions_for_result(scan_context)
        return _general_precautions()

    # ── Treatment queries ──
    if any(word in message for word in ['treatment', 'treat', 'cure', 'medicine', 'therapy', 'medication']):
        if scan_context:
            pred = scan_context.get('prediction', '')
            if pred in DISEASE_KNOWLEDGE and 'treatment' in DISEASE_KNOWLEDGE[pred]:
                d = DISEASE_KNOWLEDGE[pred]
                return (f"💊 **Treatment for {d['name']}:**\n\n"
                        f"{d['treatment']}\n\n"
                        f"👨‍⚕️ **Consult:** {d.get('specialist', 'your healthcare provider')}\n\n"
                        f"⚠️ **Disclaimer:** This is educational information only. Always follow your doctor's recommendations for treatment.")
        return ("I can provide treatment information for any detected condition. Please upload and analyze a scan first, or ask about a specific condition like:\n"
                "• \"How is pneumonia treated?\"\n"
                "• \"Treatment for glioma\"\n"
                "• \"How to treat a fracture\"")

    # ── Doctor/Specialist queries ──
    if any(word in message for word in ['doctor', 'specialist', 'consult', 'hospital', 'clinic', 'appointment']):
        if scan_context:
            pred = scan_context.get('prediction', '')
            if pred in DISEASE_KNOWLEDGE:
                d = DISEASE_KNOWLEDGE[pred]
                urgency = d.get('urgency', 'moderate')
                urgency_msg = {
                    'high': '🔴 **URGENT** — Seek medical attention as soon as possible.',
                    'moderate': '🟡 **Recommended** — Schedule an appointment within the next few days.',
                    'low': '🟢 **Routine** — Monitor and follow up at your next regular check-up.',
                    'none': '✅ **No urgent action needed** — Continue regular health check-ups.'
                }
                return (f"👨‍⚕️ **Specialist Recommendation:**\n\n"
                        f"For **{d['name']}**, you should consult a **{d.get('specialist', 'healthcare provider')}**.\n\n"
                        f"**Urgency Level:** {urgency_msg.get(urgency, urgency_msg['moderate'])}\n\n"
                        f"**Before your appointment, prepare:**\n"
                        f"• Download your scan results from the Dashboard\n"
                        f"• Note any symptoms you're experiencing\n"
                        f"• List current medications\n"
                        f"• Prepare questions for your doctor\n\n"
                        f"⚠️ This is an AI screening tool — a specialist will provide definitive diagnosis.")
        return ("Based on your scan results, I can recommend the appropriate specialist. Please analyze a scan first!")

    # ── How AI works ──
    if any(word in message for word in ['how', 'work', 'algorithm', 'technology', 'accuracy']):
        if 'accurate' in message or 'accuracy' in message:
            return _accuracy_info()
        return _how_ai_works()

    # ── Help / Capabilities ──
    if any(word in message for word in ['help', 'what can', 'feature', 'capability']):
        return _help_message()

    # ── Thank you ──
    if any(word in message for word in ['thank', 'thanks', 'appreciate']):
        return (f"You're welcome, {user_name}! 😊 I'm always here to help you understand your medical scans.\n\n"
                f"Remember: For any concerns, always consult with a qualified healthcare professional. Stay healthy! 💪")

    # ── Default (smarter fallback) ──
    return _smart_default(message, scan_context)


# ─── Assistant Helper Functions ──────────────────────────────────────

def _explain_scan_result(scan_context):
    """Generate a detailed explanation of scan results using the knowledge base."""
    pred = scan_context.get('prediction', 'Unknown')
    risk = scan_context.get('risk_score', 0)
    conf = scan_context.get('confidence', 0)
    scan_type = scan_context.get('scan_type', '')

    if pred in DISEASE_KNOWLEDGE:
        d = DISEASE_KNOWLEDGE[pred]
        urgency = d.get('urgency', 'moderate')
        urgency_icons = {'high': '🔴', 'moderate': '🟡', 'low': '🟢', 'none': '✅'}

        findings_str = '\n'.join([f"• {f}" for f in d.get('findings', [])])

        response = (f"📋 **{d.get('scan_type', 'Medical')} Analysis Summary:**\n\n"
                    f"{urgency_icons.get(urgency, '🔵')} Prediction: **{d['name']}**\n"
                    f"📊 Confidence: **{conf}%** | Risk Score: **{risk}%**\n\n"
                    f"**What this means:**\n{d['description']}\n\n"
                    f"**Key Findings:**\n{findings_str}\n\n")

        if 'symptoms' in d:
            symptoms_str = '\n'.join([f"• {s}" for s in d['symptoms'][:4]])
            response += f"**Watch for these symptoms:**\n{symptoms_str}\n\n"

        if 'treatment' in d:
            response += f"**Treatment:** {d['treatment']}\n\n"

        if 'specialist' in d:
            response += f"👨‍⚕️ **Recommended specialist:** {d['specialist']}\n\n"

        response += "⚠️ *This is an AI-assisted screening tool. Please consult a healthcare professional for definitive diagnosis and treatment.*"
        return response

    # Fallback for unknown predictions
    return (f"📋 **Scan Analysis Summary:**\n\n"
            f"Prediction: **{pred}**\n"
            f"Confidence: **{conf}%** | Risk Score: **{risk}%**\n\n"
            f"Please consult a healthcare professional for detailed evaluation.\n\n"
            f"⚠️ *This is an AI-assisted screening tool, not a definitive diagnosis.*")


def _disease_info(disease_key):
    """Return detailed information about a specific disease."""
    if disease_key not in DISEASE_KNOWLEDGE:
        return "I don't have detailed information about that condition. Please try asking about a specific condition I support."

    d = DISEASE_KNOWLEDGE[disease_key]
    response = f"{d['icon']} **About {d['name']}** ({d.get('scan_type', 'Medical')}):\n\n"
    response += f"{d['description']}\n\n"

    if 'symptoms' in d:
        symptoms_str = '\n'.join([f"• {s}" for s in d['symptoms']])
        response += f"**Common Symptoms:**\n{symptoms_str}\n\n"

    if 'treatment' in d:
        response += f"**Treatment:** {d['treatment']}\n\n"

    if 'prevention' in d:
        response += f"**Prevention:** {d['prevention']}\n\n"

    if 'specialist' in d:
        response += f"👨‍⚕️ **Specialist:** {d['specialist']}"

    return response


def _brain_tumor_overview():
    """Return an overview of brain tumor types."""
    return ("🧠 **Brain Tumor Types Our AI Can Detect:**\n\n"
            "Our brain MRI model classifies scans into **4 categories**:\n\n"
            "**1. Glioma** — Tumors arising from glial cells. Most common primary brain tumor. "
            "Can range from low-grade to aggressive. Treatment: surgery, radiation, chemo.\n\n"
            "**2. Meningioma** — Tumors from the meninges (brain membranes). Usually benign and slow-growing. "
            "Treatment: observation, surgery, or radiosurgery.\n\n"
            "**3. Pituitary Tumor** — Adenomas in the pituitary gland. Affect hormone production. "
            "Treatment: medication, surgery, radiation.\n\n"
            "**4. No Tumor** — Normal brain scan with no mass lesions detected.\n\n"
            "Ask me about any specific tumor type for more details! "
            "e.g., \"Tell me about glioma\" or \"What is meningioma?\"")


def _tb_info():
    """Return TB information."""
    return ("🦠 **About Tuberculosis (TB):**\n\n"
            "TB is caused by Mycobacterium tuberculosis bacteria. It spreads through "
            "airborne droplets when an infected person coughs or sneezes.\n\n"
            "**Common Symptoms:**\n"
            "• Persistent cough (3+ weeks)\n"
            "• Coughing up blood\n"
            "• Night sweats\n"
            "• Weight loss and fatigue\n"
            "• Fever and chills\n\n"
            "**Treatment:** TB is treatable with a 6-9 month course of antibiotics (RIPE therapy: "
            "Rifampicin, Isoniazid, Pyrazinamide, Ethambutol). Early detection is crucial.\n\n"
            "**Prevention:** BCG vaccination, avoiding close contact with TB patients, "
            "good ventilation, respiratory hygiene.\n\n"
            "👨‍⚕️ **Specialist:** Pulmonologist or infectious disease specialist")


def _retinal_overview():
    """Return an overview of retinal conditions."""
    return ("👁️ **Retinal Conditions Our AI Can Detect:**\n\n"
            "Our retinal OCT model analyzes scans for **4 categories**:\n\n"
            "**1. CNV (Choroidal Neovascularization)** — Abnormal blood vessels under the retina. "
            "Associated with wet AMD. Can cause rapid vision loss. Urgency: HIGH.\n\n"
            "**2. DME (Diabetic Macular Edema)** — Fluid leakage in the macula from diabetic retinopathy. "
            "Causes blurry central vision. Treatment: anti-VEGF injections.\n\n"
            "**3. Drusen** — Yellow deposits under the retina, early sign of AMD. "
            "Usually monitored with supplements and lifestyle changes.\n\n"
            "**4. Normal** — Healthy retina with no abnormalities detected.\n\n"
            "Ask about any specific condition for details! e.g., \"What is CNV?\" or \"Tell me about DME\"")


def _scan_types_overview():
    """Return overview of all supported scan types."""
    response = "🔬 **MediScan AI Supported Scan Types:**\n\n"
    for key, info in SCAN_TYPE_INFO.items():
        classes_str = ', '.join(info['detects'])
        response += (f"{info['icon']} **{info['name']}**\n"
                     f"   Detects: {classes_str}\n"
                     f"   Accuracy: {info['accuracy']}\n\n")
    response += "Select a scan type on the **Scan** page, upload your image, and our AI will analyze it!"
    return response


def _accuracy_info():
    """Return model accuracy information."""
    response = "📊 **MediScan AI Model Accuracy:**\n\n"
    for key, info in SCAN_TYPE_INFO.items():
        response += f"{info['icon']} **{info['name']}**: {info['accuracy']}\n"
    response += ("\n**Architecture:** MobileNetV2 (transfer learning from ImageNet)\n"
                 "**Format:** TensorFlow Lite (optimized for fast inference)\n"
                 "**Image Size:** 150×150 pixels\n\n"
                 "⚠️ These accuracies are based on validation data. Real-world performance may vary. "
                 "Always use as a screening aid, not a definitive diagnosis.")
    return response


def _precautions_for_result(scan_context):
    """Return scan-result-specific precautions."""
    pred = scan_context.get('prediction', '')
    if pred in DISEASE_KNOWLEDGE and 'prevention' in DISEASE_KNOWLEDGE[pred]:
        d = DISEASE_KNOWLEDGE[pred]
        return (f"🛡️ **Precautions for {d['name']}:**\n\n"
                f"**Prevention:** {d['prevention']}\n\n"
                f"**General Health Tips:**\n"
                f"• Maintain a balanced diet rich in nutrients\n"
                f"• Exercise regularly as recommended by your doctor\n"
                f"• Get adequate sleep (7-9 hours)\n"
                f"• Attend all scheduled follow-up appointments\n"
                f"• Take prescribed medications as directed\n\n"
                f"👨‍⚕️ Consult your **{d.get('specialist', 'doctor')}** for personalized advice.")
    return _general_precautions()


def _general_precautions():
    """Return general health precautions."""
    return ("🛡️ **General Health Precautions:**\n\n"
            "**Respiratory Health:**\n"
            "• Get vaccinated (flu, pneumonia, COVID-19)\n"
            "• Practice good hand hygiene\n"
            "• Avoid smoking and secondhand smoke\n\n"
            "**Brain Health:**\n"
            "• Stay mentally active and socially engaged\n"
            "• Manage stress and get adequate sleep\n"
            "• Report persistent headaches or vision changes\n\n"
            "**Skin Health:**\n"
            "• Use sunscreen (SPF 30+) daily\n"
            "• Perform regular skin self-exams\n"
            "• Annual dermatologist check-ups\n\n"
            "**Eye Health:**\n"
            "• Regular eye exams (annually after age 50)\n"
            "• Eat leafy greens and omega-3 rich foods\n"
            "• Manage diabetes and blood pressure\n\n"
            "**Bone Health:**\n"
            "• Calcium and Vitamin D supplementation\n"
            "• Weight-bearing exercise\n"
            "• Fall prevention measures")


def _how_ai_works():
    """Return how the AI system works."""
    return ("🤖 **How MediScan AI Works:**\n\n"
            "Our system uses **5 trained MobileNetV2 CNN models**, each specialized for a different scan type.\n\n"
            "**Architecture:**\n"
            "• Base: MobileNetV2 (pre-trained on ImageNet)\n"
            "• Transfer learning with custom classification heads\n"
            "• Optimized to TensorFlow Lite (~3-5 MB per model)\n\n"
            "**The Process:**\n"
            "1️⃣ **Select** — Choose scan type (Chest/Brain/Skin/Retinal/Bone)\n"
            "2️⃣ **Upload** — Upload your medical image (PNG/JPG)\n"
            "3️⃣ **Preprocess** — Image resized to 150×150, normalized\n"
            "4️⃣ **Analyze** — Scan-specific CNN extracts features\n"
            "5️⃣ **Predict** — Model outputs disease probabilities\n"
            "6️⃣ **Visualize** — Grad-CAM heatmap shows areas of concern\n\n"
            "**Training Data:** Models trained on curated Kaggle medical imaging datasets with "
            "GPU acceleration for optimal performance.")


def _help_message():
    """Return help / capabilities message."""
    return ("💡 **I can help you with:**\n\n"
            "📋 **Scan Results** — \"Explain my scan result\"\n"
            "🫁 **Chest X-ray** — \"What is pneumonia?\"\n"
            "🧠 **Brain Tumors** — \"Tell me about glioma\" / \"brain tumor types\"\n"
            "🔬 **Skin Cancer** — \"What is melanoma?\"\n"
            "👁️ **Eye Diseases** — \"What is CNV?\" / \"retinal diseases\"\n"
            "🦴 **Fractures** — \"Tell me about fractures\"\n"
            "💊 **Treatment** — \"How is it treated?\"\n"
            "👨‍⚕️ **Specialists** — \"Which doctor should I see?\"\n"
            "🛡️ **Prevention** — \"What precautions should I take?\"\n"
            "🤖 **AI System** — \"How does the AI work?\"\n"
            "📊 **Accuracy** — \"How accurate is the model?\"\n\n"
            "Just type your question naturally — I understand context from your latest scan!")


def _smart_default(message, scan_context):
    """Smart fallback that tries to give a useful response."""
    # If they have a scan result, offer to explain it
    if scan_context:
        pred = scan_context.get('prediction', 'Unknown')
        return (f"I'd be happy to help! Based on your latest scan result (**{pred}**), I can:\n\n"
                f"• Explain what this result means — say \"explain my result\"\n"
                f"• Suggest treatment options — say \"treatment\"\n"
                f"• Recommend a specialist — say \"which doctor\"\n"
                f"• Share precautions — say \"precautions\"\n\n"
                f"Or ask me about any medical condition by name!")

    return ("I'm MediScan AI Assistant — your medical imaging guide! 🏥\n\n"
            "I'm trained on **5 scan types** and can help with:\n"
            "• 🫁 Chest X-ray (Pneumonia)\n"
            "• 🧠 Brain MRI (Glioma, Meningioma, Pituitary)\n"
            "• 🔬 Skin Lesion (Melanoma screening)\n"
            "• 👁️ Retinal OCT (CNV, DME, Drusen)\n"
            "• 🦴 Bone X-ray (Fracture detection)\n\n"
            "**Try asking:**\n"
            "• \"What is glioma?\"\n"
            "• \"Tell me about retinal diseases\"\n"
            "• \"How does the AI work?\"\n"
            "• \"What scan types do you support?\"")


# ─── File Serving ─────────────────────────────────────────────────────

@app.route('/')
def serve_index():
    """Serve the frontend index.html."""
    return send_from_directory(FRONTEND_FOLDER, 'index.html')


@app.route('/css/<path:filename>')
def serve_css(filename):
    """Serve CSS files."""
    return send_from_directory(os.path.join(FRONTEND_FOLDER, 'css'), filename)


@app.route('/js/<path:filename>')
def serve_js(filename):
    """Serve JavaScript files."""
    return send_from_directory(os.path.join(FRONTEND_FOLDER, 'js'), filename)


@app.route('/assets/<path:filename>')
def serve_assets(filename):
    """Serve asset files."""
    return send_from_directory(os.path.join(FRONTEND_FOLDER, 'assets'), filename)


@app.route('/uploads/<filename>')
def serve_upload(filename):
    """Serve uploaded scan images."""
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route('/heatmaps/<filename>')
def serve_heatmap(filename):
    """Serve generated heatmap images."""
    return send_from_directory(HEATMAP_FOLDER, filename)


# ─── Admin Endpoint (View Users) ─────────────────────────────────────

@app.route('/api/admin/users', methods=['GET'])
def admin_users():
    """View all registered users (for admin/debugging)."""
    db = get_db()
    users = db.execute('SELECT id, full_name, username, email, created_at FROM users').fetchall()
    db.close()
    user_list = [{'id': u['id'], 'full_name': u['full_name'], 'username': u['username'],
                  'email': u['email'], 'created_at': u['created_at']} for u in users]
    return jsonify({'success': True, 'total': len(user_list), 'users': user_list})


# ─── Initialize and Run ──────────────────────────────────────────────

# Initialize DB on import (needed for production)
init_db()

if __name__ == '__main__':
    print("=" * 50)
    print("  MediScan AI - Backend Server")
    print("=" * 50)
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') != 'production'
    print(f"[Server] Starting on http://localhost:{port}")
    app.run(debug=debug, host='0.0.0.0', port=port)
