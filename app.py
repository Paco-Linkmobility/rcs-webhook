"""
Webhook para Google RCS Business Messaging (Prueba con creación de conversación)
===============================================================================

Esta versión prueba la hipótesis de que el error 404 se debe a que la conversación
no está "activa" para el agente, y debe crearse explícitamente antes de enviar
el primer mensaje.

✅ Características:
- Usa formato MSISDN/+phone (correcto para mensajes entrantes).
- Verifica existencia de conversación con GET.
- Crea conversación con POST si no existe (404).
- Corrige espacios en audience y URLs.
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

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CLIENT_TOKEN = os.environ.get("CLIENT_TOKEN", "").strip()
SECRET_FILE_PATH = "/etc/secrets/service-account.json"


def send_rcs_text(conversation_id: str, text: str) -> bool:
    """
    Envía un mensaje de texto RCS, creando la conversación si es necesario.
    
    Esta función:
    1. Verifica si la conversación existe mediante una petición GET
    2. Si la conversación no existe (error 404), la crea con una petición POST
    3. Envía el mensaje de texto a la conversación existente o recién creada
    
    Args:
        conversation_id (str): Identificador de la conversación en formato MSISDN/+número
        text (str): Texto del mensaje a enviar
        
    Returns:
        bool: True si el mensaje se envió correctamente, False en caso contrario
    """
    try:
        if not os.path.exists(SECRET_FILE_PATH):
            logger.error("❌ No se encontró service-account.json")
            return False

        with open(SECRET_FILE_PATH, "r") as f:
            sa_info = json.load(f)

        # ✅ Corregido: audience SIN espacios
        credentials = jwt.Credentials.from_service_account_info(
            sa_info,
            audience="https://businessmessages.googleapis.com/"
        )
        credentials.refresh(Request())
        token = credentials.token

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        # 1. Verificar si la conversación existe
        convo_url = f"https://businessmessages.googleapis.com/v1/{conversation_id}"
        logger.info(f"🔍 Verificando conversación: {convo_url}")
        resp = requests.get(convo_url, headers=headers, timeout=10)

        # 2. Si no existe (404), crearla
        if resp.status_code == 404:
            logger.warning("⚠️ Conversación no encontrada. Creándola...")
            create_url = "https://businessmessages.googleapis.com/v1/conversations"
            create_body = {
                "conversationId": conversation_id,
                "businessInfo": {"businessName": "MediBot"}
            }
            create_resp = requests.post(create_url, headers=headers, json=create_body, timeout=10)
            create_resp.raise_for_status()
            logger.info("✅ Conversación creada exitosamente.")

        # Si hay otro error (403, 500, etc.), lo lanzamos
        resp.raise_for_status()

        # 3. Enviar el mensaje
        message_url = f"{convo_url}/messages"
        message_body = {
            "text": text,
            "messageId": str(uuid.uuid4())
        }
        msg_resp = requests.post(message_url, headers=headers, json=message_body, timeout=10)
        msg_resp.raise_for_status()
        logger.info(f"✅ Mensaje enviado a: {conversation_id}")
        return True

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code
        error_text = e.response.text
        logger.error(f"❌ HTTPError {status}: {error_text}")
        return False
    except Exception as e:
        logger.error(f"💥 Error inesperado: {e}", exc_info=True)
        return False


@app.route("/", methods=["GET", "HEAD"])
def root():
    """
    Endpoint básico para verificación de que el servicio está funcionando.
    
    Returns:
        str: Mensaje "OK" con código de estado 200
    """
    return "OK", 200


@app.route("/health", methods=["GET"])
def health():
    """
    Endpoint de salud que verifica el estado del servicio y la disponibilidad
    de recursos necesarios (token de cliente y archivo de cuenta de servicio).
    
    Returns:
        dict: Diccionario con el estado del servicio y disponibilidad de recursos
    """
    return {
        "status": "healthy",
        "client_token_set": bool(CLIENT_TOKEN),
        "service_account_available": os.path.exists(SECRET_FILE_PATH)
    }


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Maneja las solicitudes webhook entrantes de Google RCS Business Messaging.
    
    Esta función:
    1. Procesa el payload entrante (directo o codificado en base64 para Pub/Sub)
    2. Verifica si es una solicitud de validación de webhook (clientToken/secret)
    3. Extrae el número de teléfono del remitente para formar el conversationId
    4. Envía una respuesta automática usando la función send_rcs_text
    
    Returns:
        Response: Respuesta HTTP adecuada según el procesamiento
    """
    try:
        payload = request.get_json()
        if not payload: 
            return "Invalid JSON", 400

        logger.info(f"PAYLOAD RECIBIDO:\n{json.dumps(payload, indent=2)}")

        # Decodificar Pub/Sub (Link Mobility)
        if "message" in payload and "data" in payload["message"]:
            decoded = base64.b64decode(payload["message"]["data"]).decode("utf-8")
            rcs_payload = json.loads(decoded)
            logger.info(f"📩 Mensaje decodificado:\n{json.dumps(rcs_payload, indent=2)}")
        else:
            rcs_payload = payload

        # Verificación de Google
        if "clientToken" in rcs_payload and "secret" in rcs_payload:
            if rcs_payload["clientToken"] == CLIENT_TOKEN:
                return Response(rcs_payload["secret"], status=200, mimetype="text/plain")
            else:
                return "Invalid clientToken", 403

        # Solo mensajes de texto
        if "text" not in rcs_payload:
            return "OK", 200

        sender_phone = rcs_payload.get("senderPhoneNumber")
        if not sender_phone:
            return "OK", 200

        # ✅ Usa MSISDN (formato correcto para mensajes entrantes)
        conversation_id = f"MSISDN/{sender_phone}"
        logger.info(f"🔍 Usando conversationId: {conversation_id}")

        send_rcs_text(conversation_id, "¡Hola! 👋 Soy MediBot. ¿En qué puedo ayudarte?")
        return "OK", 200

    except Exception as e:
        logger.error(f"💥 Error en webhook: {e}", exc_info=True)
        return "Internal error", 500


if __name__ == "__main__":
    """
    Punto de entrada de la aplicación.
    
    Inicia el servidor Flask en el puerto especificado (por defecto 10000)
    y escucha en todas las interfaces de red (0.0.0.0).
    """
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)