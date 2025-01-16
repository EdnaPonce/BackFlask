from flask import Flask, request, jsonify
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials
import requests
import json
from openai import OpenAI
from ocr import ocr_bp
from face_routes import face_bp

app = Flask(__name__)

# Registrar Blueprints
app.register_blueprint(ocr_bp, url_prefix='/ocr')
app.register_blueprint(face_bp, url_prefix='/face')

# Ruta al archivo JSON con las credenciales de Firebase
SERVICE_ACCOUNT_FILE = "empleame-a691c-firebase-adminsdk-vchrl-d778080d27.json"  # Cambia según tu estructura de archivos
SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]

# Obtener el token de acceso para la API HTTP v1
def get_access_token():
    credentials = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    credentials.refresh(Request())  # Refrescar el token si es necesario
    return credentials.token

@app.route('/send-notification', methods=['POST'])
def send_notification():
    try:
        # Obtener datos de la solicitud
        data = request.json
        if not data or 'deviceToken' not in data or 'title' not in data or 'body' not in data:
            return jsonify({"error": "Datos inválidos"}), 400

        device_token = data['deviceToken']
        title = data['title']
        body = data['body']

        # Crear el payload para Firebase
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
                        "icon": "soporte_tecnico",  # Nombre del icono configurado en Android
                    }
                }
            }
        }

        # Headers para la API de Firebase
        headers = {
            "Authorization": f"Bearer {get_access_token()}",
            "Content-Type": "application/json",
        }

        # URL de la API HTTP v1 de Firebase
        project_id = "empleame-a691c"  # Cambia por el ID de tu proyecto Firebase
        url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

        # Enviar la solicitud a Firebase
        response = requests.post(url, headers=headers, json=payload)

        if response.status_code == 200:
            return jsonify({"success": True, "message": "Notificación enviada correctamente"}), 200
        else:
            return jsonify({"success": False, "error": response.json()}), response.status_code

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Configuración de OpenAI
client = OpenAI(api_key="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")

@app.route('/identify-service', methods=['POST'])
def identify_service():
    try:
        # Obtener el problema enviado desde Flutter
        data = request.json
        if not data or 'problem' not in data:
            return jsonify({"error": "No se proporcionó un problema"}), 400

        problem = data['problem']

        # Llamada a la API de OpenAI
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

        # Obtener la respuesta
        service_needed = chat_completion.choices[0].message.content.strip()

        return jsonify({"service": service_needed}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)

