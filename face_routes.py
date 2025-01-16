from flask import Blueprint, request, jsonify
import face_recognition
import os
from firebase_setup import db

# Crear un Blueprint para las rutas de reconocimiento facial
face_bp = Blueprint('face', __name__)

@face_bp.route('/get_latest_worker', methods=['GET'])
def get_latest_worker():
    try:
        print("Iniciando consulta para obtener el último trabajador...")

        # Referencia a la colección usuarios
        users_ref = db.collection('usuarios')

        # Consulta: Filtrar por tipoUsuario == "trabajador", ordenar por fechaRegistro descendente
        query = users_ref.where('tipoUsuario', '==', 'trabajador').order_by('fechaRegistro', direction='DESCENDING').limit(1)
        docs = query.stream()

        # Iterar sobre los documentos obtenidos
        for doc in docs:
            data = doc.to_dict()
            print(f"Documento encontrado: {doc.id}, Datos: {data}")
            return jsonify({
                "nombre": data.get('nombre', 'Desconocido'),
                "fechaRegistro": str(data.get('fechaRegistro', 'Sin Fecha'))
            })

        # Si no se encontraron documentos
        print("No se encontró ningún trabajador.")
        return jsonify({"error": "No se encontró ningún trabajador"}), 404
    except Exception as e:
        print(f"Error al obtener el trabajador: {str(e)}")
        return jsonify({"error": str(e)}), 500

@face_bp.route('/add_reference_face', methods=['POST'])
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

    # Verifica si el archivo existe antes de procesarlo
    if not os.path.exists(image_path):
        return jsonify({"error": "La imagen no se guardó correctamente."}), 500

    try:
        # Procesar la imagen para obtener codificación facial
        image = face_recognition.load_image_file(image_path)
        face_encodings = face_recognition.face_encodings(image)

        if not face_encodings:
            os.remove(image_path)
            return jsonify({"error": "No face found"}), 400

        # Obtener la primera codificación (suponiendo que hay una sola cara)
        face_encoding = face_encodings[0].tolist()

        # Obtener el nombre del formulario
        name = request.form.get("nombre", "Unknown")

        # Subir la codificación a Firebase
        doc_ref = db.collection('autenticacion').document()
        doc_ref.set({
            "face_encoding": face_encoding,
            "nombre": name
        })

        # Eliminar imagen temporal
        os.remove(image_path)

        return jsonify({"message": "Face added as reference", "nombre": name}), 200
    except Exception as e:
        print(f"Error al procesar la imagen: {e}")
        return jsonify({"error": f"Error al procesar la imagen: {e}"}), 500
