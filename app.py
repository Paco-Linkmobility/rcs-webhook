"""
Webhook para Google RCS Business Messaging
==========================================

Este servicio:
1. Pasa la verificación de webhook de Google (clientToken + secret).
2. Recibe mensajes RCS en formato JSON plano.
3. Responde automáticamente usando la API de Google Business Messages.
4. Usa una Service Account montada como Secret File en Render.

Requisitos en Render:
- Secret File: service-account.json → en /etc/secrets/service-account.json
- Environment Variable: CLIENT_TOKEN (el que defines en Google Console)
"""

import os
import json
import logging
import uuid
from flask import Flask, request, Response
import requests
from google.auth import jwt
from google.auth.transport.requests import Request

# Configuración básica
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Leer token de verificación desde entorno
CLIENT_TOKEN = os.environ.get("CLIENT_TOKEN", "").strip()
SECRET_FILE_PATH = "/etc/secrets/service-account.json"


def send_rcs_text(conversation_id: str, text: str) -> bool:
    """
    Envía un mensaje de texto por RCS usando la API oficial.
    Basado en los ejemplos oficiales de Google.
    """
    try:
        # Cargar credenciales desde Secret File
        if not os.path.exists(SECRET_FILE_PATH):
            logger.error("❌ No se encontró el archivo de credenciales")
            return False

        with open(SECRET_FILE_PATH, "r") as f:
            sa_info = json.load(f)

        # Generar token de acceso
        credentials = jwt.Credentials.from_service_account_info(
            sa_info,
            audience="https://businessmessages.googleapis.com/",
            scopes=["https://www.googleapis.com/auth/businessmessages"]
        )
        credentials.refresh(Request())

        # Construir mensaje
        message_body = {
            "text": text,
            "messageId": str(uuid.uuid4())
        }

        # Enviar
        url = f"https://businessmessages.googleapis.com/v1/conversations/{conversation_id}/messages"
        headers = {
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json"
        }
        resp = requests.post(url, headers=headers, json=message_body, timeout=10)
        resp.raise_for_status()
        logger.info(f"✅ Mensaje enviado a: {conversation_id}")
        return True

    except Exception as e:
        logger.error(f"❌ Falló el envío a {conversation_id}: {e}")
        return False


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Maneja dos tipos de solicitudes POST:
    - Verificación de Google: {"clientToken": "...", "secret": "..."}
    - Mensajes RCS reales: {"conversationId": "...", "message": {...}, ...}
    """
    try:
        payload = request.get_json()
        if not 
            return "Invalid JSON", 400

        # ─── 1. Verificación de webhook ───────────────────────────────
        if "clientToken" in payload and "secret" in 
            if payload["clientToken"] == CLIENT_TOKEN:
                logger.info("✅ Webhook verificado por Google")
                return Response(payload["secret"], status=200, mimetype="text/plain")
            else:
                logger.warning("❌ clientToken no coincide")
                return "Invalid clientToken", 403

        # ─── 2. Mensaje RCS real ─────────────────────────────────────
        conversation_id = payload.get("conversationId")
        if not conversation_id:
            logger.warning("⚠️ Mensaje sin conversationId, ignorado")
            return "OK", 200

        # Responder con mensaje fijo (puedes personalizarlo después)
        send_rcs_text(conversation_id, "¡Hola! 👋 Soy MediBot. ¿En qué puedo ayudarte?")

        return "OK", 200

    except Exception as e:
        logger.error(f"💥 Error en /webhook: {e}", exc_info=True)
        return "Internal error", 500


@app.route("/health", methods=["GET"])
def health():
    """Endpoint para verificar que el servicio está listo."""
    return {
        "status": "healthy",
        "client_token_set": bool(CLIENT_TOKEN),
        "service_account_available": os.path.exists(SECRET_FILE_PATH)
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)