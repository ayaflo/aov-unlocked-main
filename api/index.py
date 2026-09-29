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

def get_request_data():
    """Hỗ trợ đọc dữ liệu từ cả JSON và Form URL-Encoded (như client gửi)"""
    data = {}
    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        if request.form:
            data.update(request.form.to_dict())
        if request.args:
            data.update(request.args.to_dict())
    return data

def handle_login():
    data = get_request_data()

    # Kiểm tra key auth:
    if data.get("auth") != "anhtandeptrai":
        return jsonify({"ketqua": "error", "mes": "Key không tồn tại"}), 401

    raw_bytes, gzip_bytes = get_response_data()
    if raw_bytes is None:
        return jsonify({"ketqua": "error", "mes": "Không tìm thấy file response.json"}), 500

    accept_encoding = request.headers.get("Accept-Encoding", "").lower()
    is_vercel = os.environ.get("VERCEL") == "1"

    # Giới hạn của Vercel Serverless Function là 4.5MB.
    # response.json gốc nặng ~12.5MB, sau khi nén gzip chỉ còn ~3.76MB (< 4.5MB).
    # Vì client đã gửi Accept-Encoding: gzip hoặc khi chạy trên Vercel, trả về gzip:
    if "gzip" in accept_encoding or is_vercel:
        response = Response(gzip_bytes, mimetype="application/json")
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = str(len(gzip_bytes))
        return response
    else:
        response = Response(raw_bytes, mimetype="application/json")
        response.headers["Content-Length"] = str(len(raw_bytes))
        return response

# Bắt tất cả các đường dẫn để chống lỗi 404 do Vercel rewrites (dù gọi /login, /api/index, /api/index.py hay bất cứ đâu)
@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def catch_all(path=""):
    # Nếu là POST: luôn luôn xử lý login và trả về response.json
    if request.method == "POST":
        return handle_login()

    # Nếu là GET:
    if path == "ping":
        return "pong", 200

    return jsonify({
        "status": "online",
        "message": "AOV Key Server is running successfully!",
        "endpoint": "/login",
        "path_received": path
    })

# Fallback chống 404 tuyệt đối
@app.errorhandler(404)
def fallback_404(e):
    if request.method == "POST":
        return handle_login()
    return jsonify({
        "status": "online",
        "message": "AOV Key Server is running successfully!",
        "endpoint": "/login"
    }), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
