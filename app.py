"""
Webhook para Google RCS Business Messaging
===========================================

Este webhook recibe mensajes de usuarios a través de Google RCS (Rich Communication Services)
y responde automáticamente. RCS es el protocolo de mensajería enriquecida que reemplaza
al SMS tradicional.

Flujo del sistema:
1. Usuario envía mensaje RCS → Link Mobility (proveedor) → Google Pub/Sub → Este webhook
2. Webhook procesa el mensaje y responde usando la API de RCS
3. Respuesta va al usuario a través del mismo canal

Configuración requerida:
- CLIENT_TOKEN: Token de verificación para validar que el webhook es legítimo
- service-account.json: Credenciales de servicio de Google Cloud
"""

import os
import json
import logging
import uuid
import base64
from flask import Flask, request, Response
import requests
from google.auth import jwt
from google.auth.transport.requests import Request
from google.oauth2 import service_account

# ============================================================================
# CONFIGURACIÓN INICIAL
# ============================================================================

# Crear aplicación Flask
app = Flask(__name__)

# Configurar sistema de logging para debugging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Variables de entorno y configuración
CLIENT_TOKEN = os.environ.get("CLIENT_TOKEN", "").strip()  # Token para verificación del webhook
SECRET_FILE_PATH = "/etc/secrets/service-account.json"     # Ruta al archivo de credenciales de Google

# Scopes necesarios para la API de RCS Business Messaging
RCS_SCOPES = [
    "https://www.googleapis.com/auth/rcsbusinessmessaging"
]

# ============================================================================
# FUNCIONES DE UTILIDAD PARA RCS
# ============================================================================

def get_credentials():
    """
    Obtiene las credenciales de autenticación para la API de RCS.
    
    Returns:
        google.auth.credentials.Credentials: Credenciales válidas para la API de RCS
    """
    try:
        # Verificar que existe el archivo de credenciales
        if not os.path.exists(SECRET_FILE_PATH):
            logger.error("❌ No se encontró service-account.json")
            return None
            
        # Cargar credenciales del service account
        credentials = service_account.Credentials.from_service_account_file(
            SECRET_FILE_PATH,
            scopes=RCS_SCOPES
        )
        
        # Refrescar para obtener un token válido
        credentials.refresh(Request())
        
        return credentials
    except Exception as e:
        logger.error(f"❌ Error al obtener credenciales: {e}")
        return None

def send_rcs_text(sender_phone: str, text: str, agent_id: str) -> bool:
    """
    Envía un mensaje de texto RCS al usuario.
    
    Esta función maneja toda la lógica de autenticación y envío de mensajes RCS:
    1. Obtiene las credenciales de autenticación
    2. Genera un token de acceso para autenticación
    3. Construye y envía el mensaje usando la API de RCS
    
    Args:
        sender_phone (str): Número de teléfono del destinatario en formato internacional (+34...)
        text (str): Texto del mensaje a enviar
        agent_id (str): ID del agente RCS que envía el mensaje
        
    Returns:
        bool: True si el mensaje se envió correctamente, False si hubo algún error
    """
    try:
        # ====== PASO 1: Obtener credenciales de autenticación ======
        credentials = get_credentials()
        if not credentials:
            return False
            
        # ====== PASO 2: Preparar headers HTTP con autenticación ======
        headers = {
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json"
        }

        # ====== PASO 3: Generar un ID único para el mensaje ======
        message_id = str(uuid.uuid4())
        
        # ====== PASO 4: Construir la URL del endpoint de RCS con messageId como parámetro ======
        # Formato: /v1/phones/{número}/agentMessages?messageId={id}
        # El número debe incluir el '+' (ej: +34610172116)
        url = f"https://rcsbusinessmessaging.googleapis.com/v1/phones/{sender_phone}/agentMessages?messageId={message_id}"
        
        # ====== PASO 5: Construir el cuerpo del mensaje ======
        # RCS usa el formato 'contentMessage' para mensajes de contenido
        message_body = {
            "contentMessage": {
                "text": text  # El texto del mensaje va dentro de contentMessage
            }
        }
        
        # Log para debugging
        logger.info(f"📤 Enviando mensaje RCS a: {url}")
        logger.info(f"📝 Cuerpo del mensaje: {json.dumps(message_body, indent=2)}")
        
        # ====== PASO 6: Enviar el mensaje mediante POST ======
        resp = requests.post(
            url, 
            headers=headers, 
            json=message_body, 
            timeout=10  # Timeout de 10 segundos para evitar bloqueos
        )
        
        # Lanzar excepción si el status HTTP no es 2xx
        resp.raise_for_status()
        
        logger.info(f"✅ Mensaje enviado exitosamente a: {sender_phone}")
        return True

    except requests.exceptions.HTTPError as e:
        # Error HTTP (400, 401, 403, 404, 500, etc.)
        status = e.response.status_code
        error_text = e.response.text
        logger.error(f"❌ HTTPError {status}: {error_text}")
        return False
    except Exception as e:
        # Cualquier otro error inesperado
        logger.error(f"💥 Error inesperado: {e}", exc_info=True)
        return False

# ============================================================================
# ENDPOINTS DEL WEBHOOK
# ============================================================================

@app.route("/", methods=["GET", "HEAD"])
def root():
    """
    Endpoint raíz para verificación básica del servicio.
    
    Este endpoint es útil para:
    - Verificar que el servicio está corriendo
    - Health checks de Render.com
    - Pruebas manuales rápidas
    
    Returns:
        tuple: ("OK", 200) indicando que el servicio está activo
    """
    return "OK", 200


@app.route("/health", methods=["GET"])
def health():
    """
    Endpoint de salud detallado para monitoreo.
    
    Proporciona información sobre:
    - Estado general del servicio
    - Si el CLIENT_TOKEN está configurado
    - Si el archivo de credenciales está disponible
    
    Útil para debugging y monitoreo en producción.
    
    Returns:
        dict: JSON con información de estado del servicio
    """
    return {
        "status": "healthy",
        "client_token_set": bool(CLIENT_TOKEN),
        "service_account_available": os.path.exists(SECRET_FILE_PATH)
    }


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Endpoint principal que recibe y procesa los mensajes RCS.
    
    Este endpoint maneja todo el flujo de procesamiento de mensajes:
    
    1. RECEPCIÓN: Recibe el payload de Google Pub/Sub
    2. DECODIFICACIÓN: Extrae el mensaje RCS del envelope de Pub/Sub
    3. VERIFICACIÓN: Valida el webhook si es una solicitud de verificación
    4. PROCESAMIENTO: Extrae información del remitente
    5. RESPUESTA: Envía una respuesta automática al usuario
    
    Formato del payload de Pub/Sub:
    {
        "subscription": "projects/.../subscriptions/...",
        "message": {
            "data": "base64_encoded_rcs_message",
            "attributes": {...},
            "messageId": "...",
            "publishTime": "..."
        }
    }
    
    Formato del mensaje RCS decodificado:
    {
        "senderPhoneNumber": "+34610172116",
        "messageId": "...",
        "sendTime": "...",
        "text": "Mensaje del usuario",
        "agentId": "link_mobility_..._agent@rbm.goog"
    }
    
    Returns:
        tuple: Respuesta HTTP apropiada según el procesamiento
    """
    try:
        # ====== PASO 1: Obtener y validar el JSON del request ======
        payload = request.get_json()
        if not payload: 
            logger.warning("⚠️ Request sin JSON válido")
            return "Invalid JSON", 400

        # Log del payload completo para debugging
        logger.info(f"PAYLOAD RECIBIDO:\n{json.dumps(payload, indent=2)}")

        # ====== PASO 2: Decodificar el mensaje de Pub/Sub ======
        # Los mensajes de RCS vienen envueltos en un mensaje de Pub/Sub
        # El contenido real está codificado en base64 en el campo 'data'
        if "message" in payload and "data" in payload["message"]:
            # Decodificar de base64 a string
            decoded = base64.b64decode(payload["message"]["data"]).decode("utf-8")
            # Parsear el JSON del mensaje RCS
            rcs_payload = json.loads(decoded)
            logger.info(f"📩 Mensaje decodificado:\n{json.dumps(rcs_payload, indent=2)}")
        else:
            # Si no es un mensaje de Pub/Sub, asumir que es el payload directo
            rcs_payload = payload

        # ====== PASO 3: Manejar verificación del webhook ======
        # Google envía una solicitud de verificación cuando se configura el webhook
        # Debemos responder con el 'secret' que nos envían para confirmar
        if "clientToken" in rcs_payload and "secret" in rcs_payload:
            if rcs_payload["clientToken"] == CLIENT_TOKEN:
                # Token correcto: devolver el secret para confirmar
                logger.info("✅ Verificación del webhook exitosa")
                return Response(rcs_payload["secret"], status=200, mimetype="text/plain")
            else:
                # Token incorrecto: rechazar
                logger.warning("⚠️ Token de cliente inválido en verificación")
                return "Invalid clientToken", 403

        # ====== PASO 4: Filtrar solo mensajes de texto ======
        # Ignorar otros tipos de eventos (entrega, lectura, etc.)
        if "text" not in rcs_payload:
            logger.info("ℹ️ Evento recibido sin texto, ignorando")
            return "OK", 200

        # ====== PASO 5: Extraer información del remitente ======
        sender_phone = rcs_payload.get("senderPhoneNumber")  # Número del usuario
        agent_id = rcs_payload.get("agentId")                # ID del agente RCS
        message_text = rcs_payload.get("text")               # Texto del mensaje
        
        # Validar que tenemos la información necesaria
        if not sender_phone:
            logger.warning("⚠️ Mensaje sin número de remitente")
            return "OK", 200

        # Log del mensaje recibido
        logger.info(f"💬 Mensaje recibido de {sender_phone}: {message_text}")

        # ====== PASO 6: Enviar respuesta automática ======
        # Aquí es donde normalmente procesarías el mensaje y generarías una respuesta
        # Por ahora, enviamos una respuesta genérica de bienvenida
        response_text = "¡Hola! 👋 Soy MediBot. ¿En qué puedo ayudarte?"
        
        # Enviar la respuesta usando la función de RCS
        success = send_rcs_text(sender_phone, response_text, agent_id)
        
        if success:
            logger.info(f"✅ Respuesta enviada exitosamente a {sender_phone}")
        else:
            logger.error(f"❌ Error al enviar respuesta a {sender_phone}")

        # Siempre devolver OK para que Pub/Sub no reintente
        return "OK", 200

    except json.JSONDecodeError as e:
        # Error al decodificar JSON
        logger.error(f"❌ Error decodificando JSON: {e}")
        return "Invalid JSON format", 400
    except Exception as e:
        # Cualquier otro error inesperado
        logger.error(f"💥 Error en webhook: {e}", exc_info=True)
        return "Internal error", 500

# ============================================================================
# PUNTO DE ENTRADA DE LA APLICACIÓN
# ============================================================================

if __name__ == "__main__":
    """
    Punto de entrada cuando se ejecuta el script directamente.
    
    Configura y lanza el servidor Flask:
    - Puerto: Usa la variable de entorno PORT (default: 10000)
    - Host: 0.0.0.0 para aceptar conexiones de cualquier interfaz
    - Debug: Desactivado en producción (Flask lo maneja automáticamente)
    
    Nota: En producción (Render.com), se usa Gunicorn en lugar de
    el servidor de desarrollo de Flask.
    """
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"🚀 Iniciando servidor en puerto {port}")
    app.run(host="0.0.0.0", port=port)