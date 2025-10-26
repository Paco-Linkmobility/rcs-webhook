import os
import json
import logging
from flask import Flask, request, Response

app = Flask(__name__)

CLIENT_TOKEN = os.environ.get('CLIENT_TOKEN', '')
N8N_WEBHOOK_URL = os.environ.get('N8N_WEBHOOK_URL', 'https://n8n-6jex.onrender.com/webhook/rcs-in')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        if not data:
            return "Invalid JSON", 400

        if 'clientToken' in data and 'secret' in data:
            if data['clientToken'] == CLIENT_TOKEN:
                return Response(data['secret'], status=200, mimetype='text/plain')
            else:
                return "Invalid clientToken", 403

        import requests
        requests.post(N8N_WEBHOOK_URL, json=data, timeout=5)
        return "OK", 200

    except Exception as e:
        logger.error(f"Error: {e}")
        return "Internal error", 500

@app.route('/health', methods=['GET'])
def health():
    return {"status": "ok"}

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)