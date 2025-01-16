from flask import Blueprint, request, jsonify
from PIL import Image, ImageEnhance, ImageOps
import io
import re
import face_recognition
import numpy as np
from firebase_setup import db  # Importa la conexión a Firebase
import easyocr

# Crear un Blueprint para las rutas de OCR
ocr_bp = Blueprint('ocr', __name__)

# Inicializar EasyOCR
reader = easyocr.Reader(['es', 'en'])

# Funciones de OCR con preprocesamiento
def preprocess_image(image):
    """
    Duplica los píxeles de la imagen para mejorar la resolución y realiza preprocesamiento
    para ajustar nitidez, brillo y contraste.
    """
    # Convierte la imagen a escala de grises
    image = ImageOps.grayscale(image)

    # Duplica los píxeles de la imagen (aumenta resolución internamente)
    image = image.resize((image.width * 2, image.height * 2), Image.Resampling.BICUBIC)

    # Aumentar el contraste
    contrast_enhancer = ImageEnhance.Contrast(image)
    image = contrast_enhancer.enhance(5.0)  # Factor ajustable para contraste

    # Aumentar el brillo
    brightness_enhancer = ImageEnhance.Brightness(image)
    image = brightness_enhancer.enhance(2.0)  # Factor ajustable para brillo

    return image

def recognize_text_from_image(image_bytes):
    """
    Preprocesa la imagen y extrae texto utilizando EasyOCR.
    """
    # Convertir los bytes de la imagen a un objeto Pillow
    image = Image.open(io.BytesIO(image_bytes))

    # Preprocesar la imagen
    image = preprocess_image(image)

    # Convertir la imagen a NumPy para EasyOCR
    image_np = np.array(image)

    # Realizar OCR
    text_results = reader.readtext(image_np)
    extracted_text = " ".join([result[1] for result in text_results])

    # Imprimir el texto extraído
    print("\nTexto extraído mediante OCR:")
    print(extracted_text)

    return extracted_text

def clean_text(text):
    """
    Limpia el texto extraído eliminando caracteres especiales, letras minúsculas y espacios innecesarios.
    """
    # Reemplaza caracteres especiales y dígitos fuera de lugar
    text = re.sub(r'[^\w\sÁÉÍÓÚÑ]', ' ', text)  # Elimina caracteres especiales
    text = re.sub(r'\s+', ' ', text).strip()  # Reemplaza múltiples espacios por uno solo
    text = re.sub(r'[a-z]', '', text)  # Elimina letras minúsculas
    text = re.sub(r'\d{2,}', '', text)  # Elimina números largos (ejemplo: "2031", "0925")
    return text


def extract_name_from_text(text):
    """
    Extrae el nombre completo del texto.
    """
    text = clean_text(text)
    match = re.search(r'NOMBRE\s+(SEXO\s*[HM]\s+)?([A-Z\s]+?)\s+DOMICILIO', text)
    name = match.group(2).strip() if match else None

    # Filtrar nombres que contienen caracteres extraños
    if name and re.search(r'[^A-Z\s]', name):
        name = re.sub(r'[^A-Z\s]', '', name)

    print("\nNombre extraído:")
    print(name if name else "No encontrado")
    return name

def extract_address_from_text(text):
    """
    Extrae el domicilio del texto.
    """
    text = clean_text(text)
    match = re.search(r'DOMICILIO\s+([A-Z0-9\s,]+)\s+CLAVEDEELECTOR', text)
    address = match.group(1).strip() if match else None

    # Filtrar direcciones que contienen caracteres extraños
    if address:
        address = re.sub(r'[^A-Z0-9\s,]', '', address)

    print("\nDomicilio extraído:")
    print(address if address else "No encontrado")
    return address

def extract_key_from_text(text):
    """
    Extrae la clave de elector del texto.
    """
    text = clean_text(text)
    match = re.search(r'CLAVEDEELECTOR\s+([A-Z0-9]+)\s+CURP', text)
    key = match.group(1).strip() if match else None

    print("\nClave de Elector extraída:")
    print(key if key else "No encontrado")
    return key



@ocr_bp.route('/process_image', methods=['POST'])
def process_image():
    """
    Procesa la imagen directamente desde la solicitud, extrae texto y realiza OCR y reconocimiento facial.
    """
    if 'image' not in request.files:
        return jsonify({"error": "No image file provided"}), 400

    # Leer la imagen de la solicitud
    image_file = request.files['image']
    image_bytes = image_file.read()

    # Procesar OCR
    ocr_text = recognize_text_from_image(image_bytes)

    # Extraer datos clave del texto
    name = extract_name_from_text(ocr_text)
    address = extract_address_from_text(ocr_text)
    key = extract_key_from_text(ocr_text)

    # Procesar reconocimiento facial
    try:
        image = face_recognition.load_image_file(io.BytesIO(image_bytes))
        face_encodings = face_recognition.face_encodings(image)
    except Exception as e:
        print(f"Error en el procesamiento facial: {e}")
        face_encodings = []

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

    # Imprimir resultados del reconocimiento facial
    print("\nResultados del reconocimiento facial:")
    print(f"Match: {match}")
    if match:
        print(f"Nombre coincidente: {matched_name}")
    else:
        print("No se encontró coincidencia.")

    # Subir datos a Firebase
    doc_ref = db.collection('autentificacion').document()
    doc_ref.set({
        'nombre': name,
        'domicilio': address,
        'clave_de_elector': key,
        'match': match,
        'matched_name': matched_name if match else None
    })

    # Responder con los datos procesados
    return jsonify({
        "name": name,
        "address": address,
        "clave_de_elector": key,
        "match": match,
        "matched_name": matched_name
    })
