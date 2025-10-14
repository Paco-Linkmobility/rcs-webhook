from flask import Flask, request, jsonify
import hashlib
import hmac
import base64
import json
import os
from datetime import datetime

app = Flask(__name__)

# Configuración
SECRET_KEY = os.getenv('GOOGLE_WEBHOOK_SECRET', '')  # Vacío inicialmente
PORT = int(os.getenv('PORT', 5000))

# Logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def verify_signature(request_data, signature_header):
    """
    Verifica la firma de la solicitud de Google
    Solo se ejecuta si SECRET_KEY está configurado
    """
    # Si no hay secret configurado, permitir la solicitud (fase de validación)
    if not SECRET_KEY:
        logger.info("⚠️ SECRET_KEY no configurado - Modo validación")
        return True
    
    if not signature_header:
        logger.warning("❌ No se recibió header X-Goog-Signature")
        return False
    
    try:
        # Crear el hash HMAC
        expected_signature = hmac.new(
            SECRET_KEY.encode('utf-8'),
            request_data,
            hashlib.sha512
        ).digest()
        
        # Codificar en base64
        expected_signature_b64 = base64.b64encode(expected_signature).decode('utf-8')
        
        # Comparar de forma segura
        is_valid = hmac.compare_digest(expected_signature_b64, signature_header)
        
        if is_valid:
            logger.info("✅ Firma verificada correctamente")
        else:
            logger.warning("❌ Firma inválida")
        
        return is_valid
    
    except Exception as e:
        logger.error(f"❌ Error verificando firma: {e}")
        return False


@app.route('/', methods=['GET'])
def home():
    """
    Endpoint de información
    """
    return jsonify({
        'status': 'online',
        'service': 'Google RCS Business Messaging Webhook',
        'timestamp': datetime.utcnow().isoformat(),
        'validation_mode': not bool(SECRET_KEY),
        'endpoints': {
            'webhook': '/webhook',
            'health': '/health'
        }
    }), 200


@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Endpoint principal para recibir mensajes de Google RCS
    """
    try:
        # Log de headers para debugging
        logger.info("=" * 50)
        logger.info("📨 Nueva solicitud recibida")
        logger.info(f"Headers: {dict(request.headers)}")
        
        # Obtener el contenido de la solicitud
        request_data = request.get_data()
        signature = request.headers.get('X-Goog-Signature')
        
        logger.info(f"Signature recibida: {signature if signature else 'NINGUNA'}")
        logger.info(f"Tamaño del payload: {len(request_data)} bytes")
        
        # Verificar firma (solo si SECRET_KEY está configurado)
        if not verify_signature(request_data, signature):
            logger.warning("❌ Verificación de firma falló")
            return jsonify({'error': 'Invalid signature'}), 401
        
        # Parsear JSON
        data = request.get_json()
        
        if not data:
            logger.warning("❌ No se recibió data JSON")
            return jsonify({'error': 'No data received'}), 400
        
        logger.info(f"📦 Payload recibido:\n{json.dumps(data, indent=2)}")
        
        # Determinar el tipo de evento
        event_type = detect_event_type(data)
        logger.info(f"📌 Tipo de evento: {event_type}")
        
        if event_type == 'message':
            handle_message(data)
        elif event_type == 'userStatus':
            handle_user_status(data)
        elif event_type == 'receipt':
            handle_receipt(data)
        elif event_type == 'suggestionResponse':
            handle_suggestion_response(data)
        else:
            logger.warning(f"⚠️ Tipo de evento desconocido: {list(data.keys())}")
        
        # Responder con 200 OK (MUY IMPORTANTE para validación de Google)
        logger.info("✅ Respondiendo 200 OK")
        logger.info("=" * 50)
        return jsonify({'status': 'success'}), 200
    
    except json.JSONDecodeError as e:
        logger.error(f"❌ Error parseando JSON: {e}")
        return jsonify({'error': 'Invalid JSON'}), 400
    
    except Exception as e:
        logger.error(f"❌ Error procesando webhook: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


def detect_event_type(data):
    """
    Detecta el tipo de evento recibido
    """
    if 'message' in data:
        return 'message'
    elif 'userStatus' in data:
        return 'userStatus'
    elif 'receipt' in data:
        return 'receipt'
    elif 'suggestionResponse' in data:
        return 'suggestionResponse'
    else:
        return 'unknown'


def handle_message(data):
    """
    Maneja mensajes de texto recibidos
    """
    message = data.get('message', {})
    sender_id = data.get('senderPhoneNumber', 'Unknown')
    message_id = message.get('messageId', 'Unknown')
    text = message.get('text', '')
    timestamp = data.get('sendTime', '')
    
    logger.info(f"💬 Mensaje de texto:")
    logger.info(f"   De: {sender_id}")
    logger.info(f"   ID: {message_id}")
    logger.info(f"   Texto: {text}")
    logger.info(f"   Timestamp: {timestamp}")
    
    # TODO: Aquí va tu lógica de negocio
    # - Guardar en base de datos
    # - Enviar a sistema CRM
    # - Responder automáticamente
    pass


def handle_user_status(data):
    """
    Maneja cambios de estado del usuario (typing indicators)
    """
    user_status = data.get('userStatus', {})
    sender_id = data.get('senderPhoneNumber', 'Unknown')
    is_typing = user_status.get('isTyping', False)
    
    logger.info(f"⌨️ Estado de usuario:")
    logger.info(f"   Usuario: {sender_id}")
    logger.info(f"   Estado: {'escribiendo...' if is_typing else 'detuvo de escribir'}")


def handle_receipt(data):
    """
    Maneja confirmaciones de entrega/lectura
    """
    receipt = data.get('receipt', {})
    message_id = receipt.get('messageId', 'Unknown')
    receipt_type = receipt.get('receiptType', 'Unknown')
    timestamp = data.get('sendTime', '')
    
    logger.info(f"📧 Recibo:")
    logger.info(f"   Mensaje ID: {message_id}")
    logger.info(f"   Tipo: {receipt_type}")
    logger.info(f"   Timestamp: {timestamp}")


def handle_suggestion_response(data):
    """
    Maneja respuestas a sugerencias (botones, acciones sugeridas)
    """
    suggestion_response = data.get('suggestionResponse', {})
    sender_id = data.get('senderPhoneNumber', 'Unknown')
    postback_data = suggestion_response.get('postbackData', '')
    text = suggestion_response.get('text', '')
    
    logger.info(f"🔘 Respuesta a sugerencia:")
    logger.info(f"   De: {sender_id}")
    logger.info(f"   Texto: {text}")
    logger.info(f"   Postback: {postback_data}")
    
    # TODO: Implementar lógica según el postback


@app.route('/health', methods=['GET'])
def health():
    """
    Endpoint de health check para monitoreo
    """
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'secret_configured': bool(SECRET_KEY)
    }), 200


if __name__ == '__main__':
    if not SECRET_KEY:
        logger.warning("⚠️" * 20)
        logger.warning("⚠️ MODO VALIDACIÓN: SECRET_KEY no configurado")
        logger.warning("⚠️ El webhook aceptará todas las solicitudes")
        logger.warning("⚠️ Configura GOOGLE_WEBHOOK_SECRET después de la validación")
        logger.warning("⚠️" * 20)
    
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=os.getenv('FLASK_ENV') == 'development'
    )