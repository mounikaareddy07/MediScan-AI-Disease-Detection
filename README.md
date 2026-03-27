# 🏥 MediScan AI — Intelligent Disease Detection Platform

An AI-powered medical imaging platform that uses **deep learning (MobileNetV2 + TFLite)** to detect diseases from **5 types of medical scans** — delivering fast, accurate screening to assist healthcare professionals.

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![Flask](https://img.shields.io/badge/Flask-3.0-green?logo=flask)
![TensorFlow](https://img.shields.io/badge/TFLite-2.14-orange?logo=tensorflow)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## 🔬 Supported Scan Types

| Scan Type | What it Detects | Model Architecture |
|-----------|----------------|-------------------|
| 🫁 **Chest X-ray** | Normal, Pneumonia | MobileNetV2 Transfer Learning |
| 🧠 **Brain MRI** | Glioma, Meningioma, Pituitary, No Tumor | MobileNetV2 Transfer Learning |
| 🔬 **Skin Lesion** | Benign, Malignant (Melanoma) | MobileNetV2 Transfer Learning |
| 👁️ **Retinal OCT** | CNV, DME, Drusen, Normal | MobileNetV2 Transfer Learning |
| 🦴 **Bone X-ray** | Fractured, Not Fractured | MobileNetV2 Transfer Learning |

---

## ✨ Key Features

- **🤖 Real AI Inference** — Trained CNN models using MobileNetV2 transfer learning
- **⚡ TFLite Optimized** — Lightweight models (~3-5MB each) for fast inference
- **🔥 Grad-CAM Heatmaps** — Visual attention maps showing where the AI found abnormalities
- **📊 Interactive Charts** — Disease probability distribution with Chart.js
- **💬 AI Assistant** — Built-in chatbot that explains results in plain language
- **🔒 Secure Auth** — User registration, login, and session management
- **📱 Responsive UI** — Modern dark theme with glassmorphism design
- **📋 Scan Dashboard** — Complete scan history with analytics

---

## 🛠️ Tech Stack

### Backend
- **Python 3.12** + **Flask 3.0**
- **TFLite Runtime** for model inference
- **OpenCV** for image preprocessing
- **SQLite** for database
- **Gunicorn** for production deployment

### Frontend
- **Vanilla JavaScript** (SPA architecture)
- **CSS3** with glassmorphism + dark theme
- **Chart.js** for data visualization
- **Google Fonts** (Inter, Outfit)

### AI/ML
- **MobileNetV2** (pre-trained on ImageNet)
- **Transfer Learning** with custom classification heads
- **TensorFlow Lite** for optimized inference
- **Kaggle** for GPU-accelerated training

---

## 📁 Project Structure

```
mediscan-ai/
├── backend/
│   ├── app.py                    # Flask API server
│   ├── database/
│   │   └── db.py                 # SQLite database module
│   ├── models/
│   │   ├── ai_model.py           # AI inference engine (TFLite + fallback)
│   │   ├── train_model.py        # Local training script
│   │   ├── kaggle_training_notebook.py  # Kaggle GPU training script
│   │   └── *.tflite              # Trained model files (after training)
│   ├── utils/
│   │   ├── auth.py               # Authentication utilities
│   │   └── heatmap.py            # Grad-CAM heatmap generator
│   ├── uploads/                  # Uploaded scan images
│   └── heatmaps/                 # Generated heatmap overlays
├── frontend/
│   ├── index.html                # Main HTML entry point
│   ├── css/
│   │   └── styles.css            # Complete design system
│   └── js/
│       ├── app.js                # SPA router & navigation
│       ├── pages.js              # Page templates
│       ├── scan.js               # Scan upload & analysis
│       ├── auth.js               # Login/signup handlers
│       ├── dashboard.js          # Dashboard & history
│       └── assistant.js          # AI assistant chatbot
├── requirements.txt
├── Procfile
└── render.yaml
```

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- pip

### Installation

```bash
# Clone the repository
git clone https://github.com/mounikaareddy07/MediScan-AI-Disease-Detection.git
cd MediScan-AI-Disease-Detection

# Install dependencies
pip install -r requirements.txt

# Run the server
cd backend
python app.py
```

Open **http://localhost:5000** in your browser.

---

## 🧠 Training Models on Kaggle

1. Go to [Kaggle](https://www.kaggle.com/code) → **New Notebook**
2. Enable **GPU T4 x2** in Settings
3. Add these 5 datasets via "Add Data":
   - `paultimothymooney/chest-xray-pneumonia`
   - `masoudnickparvar/brain-tumor-mri-dataset`
   - `kmader/skin-cancer-mnist-ham10000`
   - `paultimothymooney/kermany2018`
   - `bmadushanirodrigo/fracture-multi-region-x-ray-data`
4. Copy `backend/models/kaggle_training_notebook.py` into a cell
5. Run (~25-40 min on GPU)
6. Download output `.tflite` + `_classes.json` files
7. Place them in `backend/models/`

---

## 🌐 Deployment

Deployed on **Render** with auto-deploy from GitHub.

```yaml
# render.yaml
services:
  - type: web
    name: mediscan-ai
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: cd backend && gunicorn app:app
```

---

## 📸 Screenshots

### Landing Page
Modern dark theme with glassmorphism design and animated hero section.

### Scan Upload
Select from 5 scan types, drag & drop image upload with live preview.

### Analysis Results
AI prediction with confidence score, risk assessment, Grad-CAM heatmap, and interactive probability chart.

### Dashboard
Complete scan history with analytics, charts, and trend visualization.

---

## 👩‍💻 Author

**Mounika Reddy** — [@mounikaareddy07](https://github.com/mounikaareddy07)

---

## ⚠️ Disclaimer

This is an **AI-assisted screening tool** for educational purposes. It is NOT a substitute for professional medical diagnosis. Always consult qualified healthcare professionals for medical decisions.
