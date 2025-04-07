from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials
import requests
from openai import OpenAI
import os
import json
from flask_cors import CORS
import tempfile
import face_recognition

app = Flask(__name__)
CORS(app)  # Habilita CORS para todas las rutas

try:
    firebase_credentials_json = os.getenv("FIREBASE_CREDENTIALS")
    if not firebase_credentials_json:
        raise ValueError("FIREBASE_CREDENTIALS no está configurado en variables de entorno")
    
    SERVICE_ACCOUNT_DICT = json.loads(firebase_credentials_json)

    # Escribe ese dict como archivo temporal
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w")
    json.dump(SERVICE_ACCOUNT_DICT, temp_file)
    temp_file.close()
    SERVICE_ACCOUNT_PATH = temp_file.name

    # Inicializar Firebase Admin SDK
    cred = credentials.Certificate(SERVICE_ACCOUNT_DICT)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("Firebase inicializado correctamente")

except Exception as e:
    print(f"Error al inicializar Firebase: {e}")
    db = None  # Evitar que la app falle si Firebase no se inicializa


openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("OPENAI_API_KEY no está configurado en variables de entorno")

client = OpenAI(api_key=openai_api_key)

# Configuración para Firebase Cloud Messaging (FCM)
SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]

def get_access_token():
    credentials = Credentials.from_service_account_file(SERVICE_ACCOUNT_PATH, scopes=SCOPES)
    credentials.refresh(Request())
    return credentials.token

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
                        "icon": "Procfile",
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
            print("FCM error:", response.status_code, response.text)
            return jsonify({"success": False, "error": response.json()}), response.status_code
    except Exception as e:
        print("Error en /send-notification:", str(e))
        return jsonify({"error": str(e)}), 500

@app.route('/identify-service', methods=['POST'])
def identify_service():
    try:
        data = request.json
        if not data or 'problem' not in data:
            return jsonify({"error": "No se proporcionó un problema"}), 400

        problem = data['problem']
        
        allowed_services = {
            "Albañil", "Carpintero", "Herrero", "Electricista", "Plomero", "Pintor", 
            "Soldador", "Techador", "Pastelero", "Yesero", "Instalador de pisos y azulejos", "Cocinero", "Jardinero",
            "Instalador de vidrios", "Jardinero", "Vigilante", "Velador", 
            "Personal de limpieza", "Niñera", "Cuidadores de adultos mayores o enfermos",
            "Costurero", "Zapatero", "Reparador de electrodomésticos", "Paseador de perros"
        }

        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "Eres un asistente que identifica servicios necesarios según las descripciones de problemas. Responde solo con el tipo de servicio en una palabra o frase corta, seleccionando únicamente de esta lista: " + ", ".join(allowed_services) + ". Si el problema no corresponde a ninguno de estos servicios, responde 'no tenemos trabajadores para esa actividad'."
                },
                {
                    "role": "user",
                    "content": problem
                }
            ],
            model="gpt-3.5-turbo",
        )

        service_needed = chat_completion.choices[0].message.content.strip()
        
        # Verify the response is in our allowed list
        if service_needed not in allowed_services:
            service_needed = "no tenemos trabajadores para esa actividad"
            
        return jsonify({"service": service_needed}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/add_reference_face', methods=['POST'])
def add_reference_face():
    if 'image' not in request.files:
        return jsonify({"error": "No image file provided"}), 400

    image_file = request.files['image']
    image_path = "./temp_reference_image.jpg"

    try:
        # Guarda la imagen
        image_file.save(image_path)
        print(f"Imagen guardada temporalmente en: {image_path}")
    except Exception as e:
        return jsonify({"error": f"Error al guardar la imagen: {e}"}), 500

    if not os.path.exists(image_path):
        return jsonify({"error": "La imagen no se guardó correctamente."}), 500

    try:
        # Procesar la imagen para obtener codificación facial
        image = face_recognition.load_image_file(image_path)
        face_encodings = face_recognition.face_encodings(image)

        if not face_encodings:
            os.remove(image_path)
            return jsonify({"error": "No face found"}), 400

        # Obtener la primera codificación
        face_encoding = face_encodings[0].tolist()

        # Obtener el UID del formulario
        uid = request.form.get("uid")
        if not uid:
            return jsonify({"error": "UID no proporcionado"}), 400

        # Subir la codificación a Firebase usando el UID como identificador
        doc_ref = db.collection('autenticacion').document(uid)
        doc_ref.set({
            "face_encoding": face_encoding,
            "uid": uid,
            "timestamp": firestore.SERVER_TIMESTAMP
        })

        # Eliminar imagen temporal
        os.remove(image_path)

        return jsonify({
            "message": "Face added as reference",
            "uid": uid
        }), 200
        
    except Exception as e:
        print(f"Error al procesar la imagen: {e}")
        return jsonify({"error": f"Error al procesar la imagen: {e}"}), 500


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
