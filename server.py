from flask import Flask, request, jsonify
from PIL import Image
import io
import easyocr

app = Flask(__name__)

# Inicializa el lector OCR de easyocr
reader = easyocr.Reader(['es', 'en'])  # Idiomas configurados (español e inglés)

def recognize_text_from_image(image_bytes):
    # Convierte los bytes de la imagen en un objeto de imagen
    image = Image.open(io.BytesIO(image_bytes))
    
    # Realiza el reconocimiento de texto
    text_results = reader.readtext(image)
    
    # Extrae solo el texto en un formato legible
    extracted_text = " ".join([result[1] for result in text_results])
    
    return extracted_text

@app.route('/api/ocr', methods=['POST'])
def ocr():
    if 'image' not in request.files:
        return jsonify({"error": "No se ha proporcionado ninguna imagen"}), 400
    
    # Obtiene la imagen del archivo enviado
    image_file = request.files['image']
    image_bytes = image_file.read()
    
    # Llama a la función de reconocimiento de texto
    extracted_text = recognize_text_from_image(image_bytes)
    
    # Devuelve el texto extraído como JSON
    return jsonify({"extracted_text": extracted_text})

if __name__ == '__main__':
    # Ejecuta el servidor Flask
    app.run(host="0.0.0.0", port=5000, debug=True)

