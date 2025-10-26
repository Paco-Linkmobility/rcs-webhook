

```python
"""
Webhook para Google RCS Business Messaging
==========================================

Este servicio:
- Pasa la verificación de webhook de Google.
- Recibe mensajes RCS en JSON plano.
- Responde SOLO a mensajes de texto reales.
- Usa Service Account desde /etc/secrets/service-account.json.
- Requiere en Render:
    - Secret File: service-account.json
    - Env Var: CLIENT_TOKEN
"""

import os
import json
import logging
import uuid
from flask import Flask, request, Response
import requests
from google.auth import jwt
from google.auth.transport.requests import Request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuración
CLIENT_TOKEN = os.environ.get("CLIENT_TOKEN", "").strip()
SECRET_FILE_PATH = "/etc/secrets/service-account.json"


def send_rcs_text(conversation_id: str, text: str) -> bool:
    """Envía un mensaje de texto por RCS usando Service Account."""
    try:
        if not os.path.exists(SECRET_FILE_PATH):
            logger.error("❌ No se encontró service-account.json")
            return False

        with open(SECRET_FILE_PATH, "r") as f:
            sa_info = json.load(f)

        credentials = jwt.Credentials.from_service_account_info(
            sa_info,
            audience="https://businessmessages.googleapis.com/",
            scopes=["https://www.googleapis.com/auth/businessmessages"]
        )
        credentials.refresh(Request())

        message_body = {
            "text": text,
            "messageId": str(uuid.uuid4())
        }

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
        logger.error(f"❌ Error al enviar mensaje: {e}")
        return False


@app.route("/", methods=["GET", "HEAD"])
def root():
    """Health check para Render."""
    return "OK", 200


@app.route("/health", methods=["GET"])
def health():
    """Endpoint detallado de salud."""
    return {
        "status": "healthy",
        "client_token_set": bool(CLIENT_TOKEN),
        "service_account_available": os.path.exists(SECRET_FILE_PATH)
    }


@app.route("/webhook", methods=["POST"])
def webhook():
    """Maneja verificación y mensajes RCS."""
    try:
        payload = request.get_json()
        if not payload:
            logger.warning("⚠️ Solicitud sin JSON válido")
            return "Invalid JSON", 400

        # 🔍 Log completo del payload (clave para depurar)
        logger.info(f"PAYLOAD COMPLETO:\n{json.dumps(payload, indent=2)}")

        # 🟢 Verificación de Google
        if "clientToken" in payload and "secret" in payload:
            if payload["clientToken"] == CLIENT_TOKEN:
                logger.info("✅ Webhook verificado por Google")
                return Response(payload["secret"], status=200, mimetype="text/plain")
            else:
                logger.warning("❌ clientToken no coincide")
                return "Invalid clientToken", 403

        # 🚫 Ignorar eventos que no son mensajes de texto
        if "message" not in payload:
            logger.info("ℹ️ Ignorado: no es mensaje de texto. Claves: %s", list(payload.keys()))
            return "OK", 200

        # ✅ Es un mensaje de texto → responder
        conversation_id = payload.get("conversationId")
        if not conversation_id:
            logger.warning("⚠️ Mensaje sin conversationId")
            return "OK", 200

        send_rcs_text(conversation_id, "¡Hola! 👋 Soy MediBot. ¿En qué puedo ayudarte?")
        return "OK", 200

    except Exception as e:
        logger.error(f"💥 Error no controlado: {e}", exc_info=True)
        return "Internal error", 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
