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
import boto3

app = Flask(__name__)
CORS(app)  # Habilita CORS para todas las rutas

# ====================== FIREBASE ======================

try:
    firebase_credentials_json = os.getenv("FIREBASE_CREDENTIALS")
    if not firebase_credentials_json:
        raise ValueError("FIREBASE_CREDENTIALS no está configurado en variables de entorno")
    
    SERVICE_ACCOUNT_DICT = json.loads(firebase_credentials_json)

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w")
    json.dump(SERVICE_ACCOUNT_DICT, temp_file)
    temp_file.close()
    SERVICE_ACCOUNT_PATH = temp_file.name

    cred = credentials.Certificate(SERVICE_ACCOUNT_DICT)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("Firebase inicializado correctamente")

except Exception as e:
    print(f"Error al inicializar Firebase: {e}")
    db = None  # Evitar que la app falle si Firebase no se inicializa

# ====================== OPENAI ======================

openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("OPENAI_API_KEY no está configurado en variables de entorno")

client = OpenAI(api_key=openai_api_key)

# ====================== AWS ======================

AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-2")

# Cliente boto3 por si luego necesitas Textract, Rekognition, etc.
rekognition_client = boto3.client(
    'rekognition',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION
)
# Directorio donde se almacenarán las imágenes de referencia (localmente)
REFERENCE_FOLDER = './reference_faces'
os.makedirs(REFERENCE_FOLDER, exist_ok=True)

# ID de la colección de rostros
COLLECTION_ID = "face_auth_collection"
# ====================== FCM ======================

SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]

def get_access_token():
    credentials = Credentials.from_service_account_file(SERVICE_ACCOUNT_PATH, scopes=SCOPES)
    credentials.refresh(Request())
    return credentials.token

@app.route("/send-notification", methods=["POST"])
def send_notification():
    try:
        data = request.json or {}

        # --- 1) Validación de campos obligatorios ---------------------------
        required_base = ["deviceToken", "title", "body"]
        if any(key not in data for key in required_base):
            return jsonify({"error": "Faltan campos obligatorios"}), 400

        device_token = data["deviceToken"]
        title        = data["title"]
        body         = data["body"]

        # --- 2) Construir el mensaje FCM ------------------------------------
        message = {
            "token": device_token,
            "notification": {
                "title": title,
                "body":  body,
                # <- esto es lo que hace que el toque abra tu app
                "click_action": "FLUTTER_NOTIFICATION_CLICK",
            },
            "android": {
                "priority": "HIGH",
                "notification": {
                    "icon": "Procfile",
                    # puedes declarar channel_id aquí si usas canales
                },
            },
        }

        # --- 3) Agregar data opcional (uid, solicitudId, userName, route) ---
        data_fields = {}
        for key in ("uid", "solicitudId", "userName", "route"):
            if key in data:
                data_fields[key] = str(data[key])

        if data_fields:
            message["data"] = data_fields

        payload = {"message": message}
        print("Payload FCM:\n", json.dumps(payload, indent=2))

        # --- 4) Enviar a la API de FCM v1 -----------------------------------
        project_id = "empleame-a691c"
        url        = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
        headers    = {
            "Authorization": f"Bearer {get_access_token()}",
            "Content-Type":  "application/json",
        }

        response = requests.post(url, headers=headers, json=payload)

        if response.ok:
            return jsonify({
                "success": True,
                "message": "Notificación enviada correctamente"
            }), 200

        # Si FCM devolvió error:
        print("FCM error:", response.status_code, response.text)
        return jsonify({
            "success": False,
            "error": response.json()
        }), response.status_code

    except Exception as e:
        print("Error en /send-notification:", e)
        return jsonify({"error": str(e)}), 500


# ====================== IDENTIFICAR SERVICIO ======================

@app.route('/identify-service', methods=['POST'])
def identify_service():
    try:
        data = request.json
        if not data or 'problem' not in data:
            return jsonify({"error": "No se proporcionó un problema"}), 400

        problem = data['problem']
        
        allowed_services = {
            "Albañil", "Carpintero", "Herrero", "Electricista", "Plomero", "Pintor", 
            "Soldador", "Techador", "Patelero", "Yesero", "Instalador de pisos y azulejos", 
            "Instalador de vidrios", "Jardinero", "Vigilante", "Velador", 
            "Personal de limpieza", "Niñera", "Cuidadores de adultos mayores o enfermos",
            "Costurero", "Zapatero", "Reparador de electrodomésticos", "Paseador de perros",
            "Pastelero", "Manicurista"
        }

        system_prompt = """
        Eres un asistente que identifica servicios necesarios según problemas domésticos. 
        Debes responder **exclusivamente** con una de estas opciones (sin cambios): 
        Albañil, Carpintero, Herrero, Electricista, Plomero, Pintor, Soldador, Techador, Yesero, Instalador de pisos y azulejos, Instalador de vidrios, Jardinero, 
        Vigilante, Velador, Personal de limpieza, Niñera, Cuidadores de adultos mayores o enfermos,
        Costurero, Zapatero, Reparador de electrodomésticos, Paseador de perros, Pastelero, Manicurista.

        Ejemplos:
        - "Se rompió una silla de madera" → Carpintero
        - "El fregadero está tapado" → Plomero
        - "Necesito instalar un piso" → Instalador de pisos y azulejos
        - "Se fue la luz en mi casa" → Electricista
        Si el problema no coincide con ningún servicio de la lista, responde: "no tenemos trabajadores disponibles".
        """

        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": problem}
            ],
            model="gpt-3.5-turbo",
            temperature=0.2
        )

        service_needed = chat_completion.choices[0].message.content.strip()
        
        if service_needed not in allowed_services:
            service_needed = "no tenemos trabajadores disponibles"
            
        return jsonify({"service": service_needed}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ====================== START APP ======================
def ensure_collection_exists():
    try:
        collections = rekognition_client.list_collections()
        app.logger.info(f"Colecciones existentes: {collections}")
        
        if COLLECTION_ID not in collections.get('CollectionIds', []):
            rekognition_client.create_collection(CollectionId=COLLECTION_ID)
            app.logger.info(f"Colección {COLLECTION_ID} creada con éxito")
        else:
            app.logger.info(f"La colección {COLLECTION_ID} ya existe")
    except Exception as e:
        app.logger.error(f"Error al verificar/crear colección: {e}")

@app.route('/add_reference_face', methods=['POST'])
def add_reference_face():
    app.logger.info("Request received for add_reference_face")
    app.logger.info(f"Form data: {request.form}")
    app.logger.info(f"Files: {request.files}")
    
    if 'image' not in request.files:
        return jsonify({"error": "No se proporcionó una imagen"}), 400
    if 'uid' not in request.form:
        return jsonify({"error": "UID no proporcionado"}), 400

    uid = request.form['uid']
    if not uid:
        return jsonify({"error": "El UID no puede estar vacío"}), 400

    image_file = request.files['image']
    reference_image_path = os.path.join(REFERENCE_FOLDER, f"{uid}.jpg")

    try:
        image_file.save(reference_image_path)
        app.logger.info(f"Imagen de referencia guardada en: {reference_image_path}")
        
        with open(reference_image_path, 'rb') as image:
            response = rekognition_client.index_faces(
                CollectionId=COLLECTION_ID,
                Image={'Bytes': image.read()},
                ExternalImageId=uid,
                DetectionAttributes=['ALL']
            )
            app.logger.info(f"Cara indexada en Rekognition: {response}")
    except Exception as e:
        app.logger.error(f"Error al guardar/indexar la imagen: {str(e)}")
        return jsonify({"error": f"Error al procesar la imagen: {str(e)}"}), 500

    return jsonify({"message": "Imagen de referencia guardada exitosamente", "uid": uid}), 200

@app.route('/compare_face', methods=['POST'])
def compare_face():
    app.logger.info("Request received for compare_face")
    app.logger.info(f"Form data: {request.form}")
    app.logger.info(f"Files: {request.files}")
    
    if 'image' not in request.files:
        return jsonify({"error": "No se proporcionó una imagen"}), 400
    if 'uid' not in request.form:
        return jsonify({"error": "UID no proporcionado"}), 400

    uid = request.form['uid']
    if not uid:
        return jsonify({"error": "El UID no puede estar vacío"}), 400

    image_file = request.files['image']

    try:
        image_bytes = image_file.read()
    except Exception as e:
        app.logger.error(f"Error al leer la imagen: {str(e)}")
        return jsonify({"error": f"Error al leer la imagen: {str(e)}"}), 500

    reference_image_path = os.path.join(REFERENCE_FOLDER, f"{uid}.jpg")
    app.logger.info(f"Looking for reference image at: {reference_image_path}")
    app.logger.info(f"File exists: {os.path.exists(reference_image_path)}")

    if not os.path.exists(reference_image_path):
        return jsonify({"error": "Imagen de referencia no encontrada para el UID proporcionado"}), 404

    try:
        with open(reference_image_path, 'rb') as ref_file:
            reference_bytes = ref_file.read()
    except Exception as e:
        app.logger.error(f"Error al leer la imagen de referencia: {str(e)}")
        return jsonify({"error": f"Error al leer la imagen de referencia: {str(e)}"}), 500

    try:
        response = rekognition_client.compare_faces(
            SourceImage={'Bytes': reference_bytes},
            TargetImage={'Bytes': image_bytes},
            SimilarityThreshold=80
        )
        app.logger.info(f"Resultado de comparación: {response}")
    except Exception as e:
        app.logger.error(f"Error al llamar a Rekognition: {str(e)}")
        return jsonify({"error": f"Error al llamar a Rekognition: {str(e)}"}), 500

    face_matches = response.get('FaceMatches', [])
    if not face_matches:
        return jsonify({"match": False, "message": "Las imágenes no coinciden."}), 200

    similarity = face_matches[0].get('Similarity', 0)
    return jsonify({"match": True, "similarity": similarity, "message": "Las imágenes coinciden."}), 200

@app.route('/extract_text', methods=['POST'])
def extract_text():
    app.logger.info("Request received for extract_text")

    if 'image' not in request.files:
        return jsonify({"error": "No se proporcionó una imagen"}), 400

    image_file = request.files['image']
    image_bytes = image_file.read()

    try:
        textract_client = boto3.client(
            'textract',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )

        response = textract_client.detect_document_text(
            Document={'Bytes': image_bytes}
        )

        lines = [
            block['Text'] for block in response.get('Blocks', [])
            if block['BlockType'] == 'LINE'
        ]

        texto_extraido = "\n".join(lines)
        app.logger.info(f"Texto extraído:\n{texto_extraido}")

        return jsonify({"text": texto_extraido}), 200

    except Exception as e:
        app.logger.error(f"Error al procesar la imagen con Textract: {str(e)}")
        return jsonify({"error": f"Error al procesar la imagen con Textract: {str(e)}"}), 500
        
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
