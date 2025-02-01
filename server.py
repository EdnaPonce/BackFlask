from flask import Flask, request, jsonify
import easyocr
from PIL import Image
import io
import re
import firebase_admin
from firebase_admin import credentials, firestore
import face_recognition
import numpy as np
import os
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials
import requests
import json
from openai import OpenAI

app = Flask(__name__)

try:
    firebase_credentials_json = os.getenv("FIREBASE_CREDENTIALS")  # Leer JSON desde variable de entorno
    if not firebase_credentials_json:
        raise ValueError("FIREBASE_CREDENTIALS no está configurado en variables de entorno")

    cred = credentials.Certificate(json.loads(firebase_credentials_json))  # Convertir string a dict
    initialize_app(cred)
    db = firestore.client()
    print("Firebase inicializado correctamente")
except Exception as e:
    print(f"Error al inicializar Firebase: {e}")
    db = None  # Evitar que la app falle si Firebase no se inicializa

# Inicializar EasyOCR
reader = easyocr.Reader(['es', 'en'])

openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("OPENAI_API_KEY no está configurado en variables de entorno")

client = OpenAI(api_key=openai_api_key

# Configuración para Firebase Cloud Messaging (FCM)
SERVICE_ACCOUNT_FILE = json.loads(firebase_credentials_json)
SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]


# Obtener el token de acceso para la API HTTP v1
def get_access_token():
    credentials = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    credentials.refresh(Request())
    return credentials.token
# Ruta para enviar notificaciones push
@app.route('/send-notification', methods=['POST'])
def send_notification():
    try:
        data = request.json
        if not data or 'deviceToken' not in data or 'title' not in data or 'body' not in data:
            return jsonify({"error": "Datos inválidos"}), 400

        device_token = data['deviceToken']
        title = data['title']
        body = data['body']

        payload = {
            "message": {
                "token": device_token,
                "notification": {
                    "title": title,
                    "body": body,
                },
                "android": {
                    "priority": "HIGH",
                    "notification": {
                        "icon": "soporte_tecnico",
                    }
                }
            }
        }

        headers = {
            "Authorization": f"Bearer {get_access_token()}",
            "Content-Type": "application/json",
        }

        project_id = "empleame-a691c"
        url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

        response = requests.post(url, headers=headers, json=payload)

        if response.status_code == 200:
            return jsonify({"success": True, "message": "Notificación enviada correctamente"}), 200
        else:
            return jsonify({"success": False, "error": response.json()}), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Ruta para identificar el servicio necesario
@app.route('/identify-service', methods=['POST'])
def identify_service():
    try:
        data = request.json
        if not data or 'problem' not in data:
            return jsonify({"error": "No se proporcionó un problema"}), 400

        problem = data['problem']

        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "Eres un asistente que identifica servicios necesarios según las descripciones de problemas. Responde solo con el tipo de servicio en una palabra, como 'electricista', 'fontanero', 'costurero', etc."
                },
                {
                    "role": "user",
                    "content": problem
                }
            ],
            model="gpt-3.5-turbo",
        )

        service_needed = chat_completion.choices[0].message.content.strip()
        return jsonify({"service": service_needed}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
# Funciones de OCR
def recognize_text_from_image(image_bytes):
    image = Image.open(io.BytesIO(image_bytes))
    text_results = reader.readtext(image)
    extracted_text = " ".join([result[1] for result in text_results])
    return extracted_text

def extract_name_from_text(text):
    match = re.search(r'SEXO\s*[HM]\s+([A-Z\s]+)\s+DOMICILIO', text)
    return match.group(1).strip() if match else None

def extract_address_from_text(text):
    match = re.search(r'DOMICILIO\s+(.+?)\s+(?:CLAVEDEELECTOR|CURP|AÑODE REGISTRO|ANODE REGISTRO|AÑO DE REGISTRO)', text)
    return match.group(1).strip() if match else None

def extract_key_from_text(text):
    match = re.search(r'CLAVEDEELECTOR\s*([A-Z0-9]+)\s*CURP', text)
    return match.group(1).strip() if match else None

# Ruta para procesar OCR y reconocimiento facial
@app.route('/ocr/process_image', methods=['POST'])
def process_image():
    if 'image' not in request.files:
        return jsonify({"error": "No image file provided"}), 400

    image_file = request.files['image']
    image_path = "./temp_image.jpg"
    image_file.save(image_path)

    try:
        with open(image_path, "rb") as image_bytes:
            ocr_text = recognize_text_from_image(image_bytes.read())

        name = extract_name_from_text(ocr_text)
        address = extract_address_from_text(ocr_text)
        key = extract_key_from_text(ocr_text)

        # Procesar reconocimiento facial
        image = face_recognition.load_image_file(image_path)
        face_encodings = face_recognition.face_encodings(image)
        match = False
        matched_name = None

        if face_encodings:
            face_encoding = face_encodings[0]
            users_ref = db.collection('autenticacion')
            docs = users_ref.stream()

            for doc in docs:
                data = doc.to_dict()
                stored_encoding = np.array(data.get('face_encoding', []))
                if stored_encoding.size > 0:
                    matches = face_recognition.compare_faces([stored_encoding], face_encoding)
                    if matches[0]:
                        match = True
                        matched_name = data['nombre']
                        break

        doc_ref = db.collection('autenticacion').document()
        doc_ref.set({
            'nombre': name,
            'domicilio': address,
            'clave_de_elector': key,
            'match': match,
            'matched_name': matched_name if match else None
        })

        return jsonify({
            "name": name,
            "address": address,
            "clave_de_elector": key,
            "match": match,
            "matched_name": matched_name
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        os.remove(image_path)

# Ruta para obtener el último trabajador registrado
@app.route('/face/get_latest_worker', methods=['GET'])
def get_latest_worker():
    if db is None:
        return jsonify({"error": "Firebase no inicializado"}), 500

    try:
        users_ref = db.collection('usuarios')
        query = users_ref.where("tipoUsuario", "==", "trabajador") \
                         .order_by("fechaRegistro", direction=firestore.Query.DESCENDING) \
                         .limit(1)
        docs = list(query.stream())

        if not docs:
            return jsonify({"error": "No se encontró ningún trabajador"}), 404

        data = docs[0].to_dict()
        return jsonify({
            "nombre": data.get('nombre', 'Desconocido'),
            "fechaRegistro": data.get('fechaRegistro', 'Sin Fecha')
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Ruta para agregar una referencia facial
@app.route('/face/add_reference_face', methods=['POST'])
def add_reference_face():
    if 'image' not in request.files:
        return jsonify({"error": "No image file provided"}), 400

    image_file = request.files['image']
    image_path = "./temp_reference_image.jpg"
    image_file.save(image_path)

    try:
        image = face_recognition.load_image_file(image_path)
        face_encodings = face_recognition.face_encodings(image)

        if not face_encodings:
            return jsonify({"error": "No face found"}), 400

        face_encoding = face_encodings[0].tolist()
        name = request.form.get("nombre", "Unknown")

        doc_ref = db.collection('autenticacion').document()
        doc_ref.set({
            "face_encoding": face_encoding,
            "nombre": name
        })

        return jsonify({"message": "Face added as reference", "nombre": name}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        os.remove(image_path)

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)

