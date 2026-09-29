import os
import json
import gzip
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# Cache dữ liệu vào RAM để tối ưu tốc độ và không phải đọc ổ đĩa mỗi request
_cached_raw_bytes = None
_cached_gzip_bytes = None

def get_response_data():
    global _cached_raw_bytes, _cached_gzip_bytes
    if _cached_raw_bytes is None:
        possible_paths = [
            os.path.join(os.path.dirname(__file__), "..", "response.json"),
            os.path.join(os.path.dirname(__file__), "response.json"),
            os.path.join(os.getcwd(), "response.json"),
            "response.json"
        ]
        json_path = None
        for p in possible_paths:
            if os.path.exists(p):
                json_path = p
                break

        if json_path and os.path.exists(json_path):
            with open(json_path, "rb") as f:
                _cached_raw_bytes = f.read()
            _cached_gzip_bytes = gzip.compress(_cached_raw_bytes)
        else:
            return None, None

    return _cached_raw_bytes, _cached_gzip_bytes

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "message": "AOV Key Server is running successfully!",
        "endpoint": "/login"
    })

@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    
    # Kiểm tra key auth nếu muốn bật:
    # if data.get("auth") != "anhtandeptrai":
    #     return jsonify({"ketqua": "error", "mes": "Key không tồn tại"}), 401

    raw_bytes, gzip_bytes = get_response_data()
    if raw_bytes is None:
        return jsonify({"ketqua": "error", "mes": "Không tìm thấy file response.json"}), 500

    accept_encoding = request.headers.get("Accept-Encoding", "").lower()
    is_vercel = os.environ.get("VERCEL") == "1"

    # Giới hạn của Vercel Serverless Function là 4.5MB.
    # response.json gốc nặng ~12.5MB, sau khi nén gzip chỉ còn ~3.76MB (< 4.5MB).
    # Vì vậy trên Vercel, hoặc khi client hỗ trợ gzip, ta bắt buộc trả về dạng nén gzip.
    if "gzip" in accept_encoding or is_vercel:
        response = Response(gzip_bytes, mimetype="application/json")
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = str(len(gzip_bytes))
        return response
    else:
        # Nếu chạy trên local hoặc server không giới hạn payload và client không hỗ trợ gzip
        response = Response(raw_bytes, mimetype="application/json")
        response.headers["Content-Length"] = str(len(raw_bytes))
        return response

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
