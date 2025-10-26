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
    return "OK", 200


@app.route("/health", methods=["GET"])
def health():
    return {
        "status": "healthy",
        "client_token_set": bool(CLIENT_TOKEN),
        "service_account_available": os.path.exists(SECRET_FILE_PATH)
    }


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        payload = request.get_json()
        if not payload:
            logger.warning("⚠️ Solicitud sin JSON válido")
            return "Invalid JSON", 400

        logger.info(f"PAYLOAD RECIBIDO:\n{json.dumps(payload, indent=2)}")

        # Detectar y decodificar mensaje de Pub/Sub (Link Mobility / 360Dialog)
        if "message" in payload and "data" in payload["message"]:
            decoded_bytes = base64.b64decode(payload["message"]["data"])
            rcs_payload = json.loads(decoded_bytes.decode("utf-8"))
            logger.info(f"📩 Mensaje RCS decodificado:\n{json.dumps(rcs_payload, indent=2)}")
        else:
            rcs_payload = payload

        # Verificación de Google (solo si es una solicitud de verificación)
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

        sender_phone = rcs_payload.get("senderPhoneNumber")
        if not sender_phone:
            logger.warning("⚠️ Mensaje sin senderPhoneNumber")
            return "OK", 200

        # Construir conversationId según estándar de Google RCS
        conversation_id = f"MSISDN/{sender_phone}"

        # Enviar respuesta automática
        send_rcs_text(conversation_id, "¡Hola! 👋 Soy MediBot. ¿En qué puedo ayudarte?")
        return "OK", 200

    except Exception as e:
        logger.error(f"💥 Error no controlado: {e}", exc_info=True)
        return "Internal error", 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)