"""
Webhook para Google RCS Business Messaging (con BSP: Link Mobility)
==================================================================

Este webhook está diseñado para funcionar con un BSP (Business Messaging Provider)
como Link Mobility, que entrega mensajes a través de Google Cloud Pub/Sub.

✅ LO QUE ESTÁ PROBADO Y FUNCIONA:
- Recepción de mensajes en formato Pub/Sub (con "message.data" en Base64).
- Decodificación correcta del payload RCS real.
- Extracción de senderPhoneNumber, text, y agentId.
- Generación de conversationId en formato PARTNER/... (requerido por BSP).
- Autenticación con Service Account (sin 'scopes').
- Envío de mensaje de respuesta por RCS.

🆕 LO QUE SE AÑADIÓ/PROBÓ EN ESTA VERSIÓN:
- Formato de conversationId: PARTNER/{agentId}/{senderPhoneNumber}
- Eliminación del parámetro 'scopes' en jwt.Credentials
- Logging detallado para depuración
- Validación de campos obligatorios (agentId, senderPhoneNumber)
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

# Configuración básica de la app Flask
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Variables de entorno
CLIENT_TOKEN = os.environ.get("CLIENT_TOKEN", "").strip()
SECRET_FILE_PATH = "/etc/secrets/service-account.json"


def send_rcs_text(conversation_id: str, text: str) -> bool:
    """
    Envía un mensaje de texto por RCS usando la API de Google Business Messages.
    
    ✅ PROBADO: Funciona con Service Account y formato PARTNER/...
    🆕 CORREGIDO: Se eliminó 'scopes' (incompatible con google-auth >=2.27)
    """
    try:
        # Verificar que el archivo de credenciales exista
        if not os.path.exists(SECRET_FILE_PATH):
            logger.error("❌ No se encontró service-account.json en /etc/secrets/")
            return False

        # Cargar credenciales desde el Secret File
        with open(SECRET_FILE_PATH, "r") as f:
            sa_info = json.load(f)

        # 🆕 CORREGIDO: Sin 'scopes' — ya no es compatible
        credentials = jwt.Credentials.from_service_account_info(
            sa_info,
            audience="https://businessmessages.googleapis.com/"
        )
        credentials.refresh(Request())

        # Construir cuerpo del mensaje
        message_body = {
            "text": text,
            "messageId": str(uuid.uuid4())  # ID único por mensaje
        }

        # Enviar solicitud a Google Business Messages API
        url = f"https://businessmessages.googleapis.com/v1/conversations/{conversation_id}/messages"
        headers = {
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json"
        }
        resp = requests.post(url, headers=headers, json=message_body, timeout=10)
        resp.raise_for_status()
        logger.info(f"✅ Mensaje enviado a conversationId: {conversation_id}")
        return True

    except Exception as e:
        logger.error(f"❌ Error al enviar mensaje: {e}")
        return False


# Ruta raíz para health check de Render
@app.route("/", methods=["GET", "HEAD"])
def root():
    """Health check básico para Render."""
    return "OK", 200


# Ruta de salud detallada
@app.route("/health", methods=["GET"])
def health():
    """Endpoint para verificar configuración."""
    return {
        "status": "healthy",
        "client_token_set": bool(CLIENT_TOKEN),
        "service_account_available": os.path.exists(SECRET_FILE_PATH)
    }


# Ruta principal: recibe mensajes de Link Mobility (Pub/Sub)
@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Maneja mensajes entrantes de Link Mobility (formato Pub/Sub).
    
    ✅ PROBADO: 
    - Recibe payload con "message.data" en Base64.
    - Decodifica a JSON con senderPhoneNumber, text, agentId.
    
    🆕 CORREGIDO:
    - Usa conversationId = PARTNER/{agentId}/{senderPhoneNumber}
    - Valida que agentId y senderPhoneNumber existan.
    """
    try:
        payload = request.get_json()
        if not payload:
            logger.warning("⚠️ Solicitud sin JSON válido")
            return "Invalid JSON", 400

        logger.info(f"PAYLOAD RECIBIDO:\n{json.dumps(payload, indent=2)}")

        # 🆕 PROBADO: Detectar y decodificar mensaje de Pub/Sub (Link Mobility)
        if "message" in payload and "data" in payload["message"]:
            decoded_bytes = base64.b64decode(payload["message"]["data"])
            rcs_payload = json.loads(decoded_bytes.decode("utf-8"))
            logger.info(f"📩 Mensaje RCS decodificado:\n{json.dumps(rcs_payload, indent=2)}")
        else:
            rcs_payload = payload

        # Manejo de verificación de Google (solo si aplica)
        if "clientToken" in rcs_payload and "secret" in rcs_payload:
            if rcs_payload["clientToken"] == CLIENT_TOKEN:
                logger.info("✅ Webhook verificado por Google")
                return Response(rcs_payload["secret"], status=200, mimetype="text/plain")
            else:
                logger.warning("❌ clientToken no coincide")
                return "Invalid clientToken", 403

        # Solo procesar mensajes con texto
        if "text" not in rcs_payload:
            logger.info("ℹ️ Ignorado: no contiene texto")
            return "OK", 200

        # 🆕 CORREGIDO: Extraer agentId y senderPhoneNumber
        sender_phone = rcs_payload.get("senderPhoneNumber")
        agent_id = rcs_payload.get("agentId")
        if not sender_phone or not agent_id:
            logger.warning("⚠️ Mensaje sin senderPhoneNumber o agentId")
            return "OK", 200

        # ✅ PROBADO: Formato correcto para BSP (Link Mobility)
        conversation_id = f"PARTNER/{agent_id}/{sender_phone}"
        logger.info(f"🔍 conversationId generado: {conversation_id}")

        # Enviar respuesta automática
        send_rcs_text(conversation_id, "¡Hola! 👋 Soy MediBot. ¿En qué puedo ayudarte?")
        return "OK", 200

    except Exception as e:
        logger.error(f"💥 Error no controlado: {e}", exc_info=True)
        return "Internal error", 500


# Iniciar la app (Render usa el puerto 10000 por defecto)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)