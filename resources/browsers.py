from flask import Flask, request, jsonify
from flask_cors import CORS

from mydb.models import GoogleMessageModel

app = Flask(__name__)
# CORS(app)
CORS(app, origins=["https://messages.google.com"])


@app.route('/', methods=['GET'])
def index():
    return {"message": "hello there!"}, 200


@app.route('/add', methods=['POST'])
def save_new_data():
    try:
        data = request.json  # Alternative: request.get_json(force=True)
        if not data:
            raise ValueError("No JSON data received")

        # ActiveWindowModel.update(duration=duration).where(ActiveWindowModel.id == self.last_id).execute()

        model = GoogleMessageModel.create(
            sent_to=data['sent_to'],
            message_id=data['message_id'],
            message=data['message']
        )
        if model.id:
            return jsonify({"message": "Success", "newid": model.id}), 200
        else:
            return jsonify({"message": "failed"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/status', methods=['POST'])
def update_status_data():
    try:
        data = request.json  # Alternative: request.get_json(force=True)
        if not data:
            raise ValueError("No JSON data received")

        GoogleMessageModel.update(status=data['status']).where(GoogleMessageModel.id == data['id']).execute()

        return jsonify({"message": "success"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    app.run(port=5000, debug=True)
