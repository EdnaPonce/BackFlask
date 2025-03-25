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


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
