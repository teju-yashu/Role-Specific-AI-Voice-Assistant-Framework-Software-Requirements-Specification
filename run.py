from flask import Flask, jsonify
from flask_cors import CORS

PROJECT_NAME = "Role-Specific AI Voice Assistant Framework for Organizations and Entities"

app = Flask(__name__)
CORS(app)


@app.get("/")
def index():
    return jsonify(
        {
            "project_name": PROJECT_NAME,
            "status": "Backend is running",
        }
    )


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "healthy",
            "service": PROJECT_NAME,
        }
    )


if __name__ == "__main__":
    # Use Flask's debug server only for local development.
    app.run(debug=True, port=5000)
