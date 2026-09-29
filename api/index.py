import os
import json
import gzip
import time
import urllib.request
import urllib.parse
from flask import Flask, request, jsonify, Response, redirect

app = Flask(__name__)

# ==========================================
# 1. CẤU HÌNH & CACHE CHO AOV LOGIN SERVER
# ==========================================
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
    """Hỗ trợ đọc dữ liệu từ cả JSON và Form URL-Encoded"""
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

    if "gzip" in accept_encoding or is_vercel:
        response = Response(gzip_bytes, mimetype="application/json")
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = str(len(gzip_bytes))
        return response
    else:
        response = Response(raw_bytes, mimetype="application/json")
        response.headers["Content-Length"] = str(len(raw_bytes))
        return response

# ==========================================
# 2. XỬ LÝ LƯU TRỮ VÀ SERVE LINK ẢNH CỐ ĐỊNH
# ==========================================
DEFAULT_IMAGE_URL = "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=800&q=80"
_memory_image_config = None

def get_storage_info():
    kv_url = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
    kv_token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    if kv_url and kv_token:
        return "Vercel KV (Lưu vĩnh viễn)", True
    return "Bộ nhớ tạm thời (RAM/Tmp)", False

def get_current_image_config():
    global _memory_image_config
    if _memory_image_config:
        return _memory_image_config

    # 1. Thử lấy từ Vercel KV / Upstash Redis nếu có
    kv_url = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
    kv_token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    if kv_url and kv_token:
        try:
            req = urllib.request.Request(f"{kv_url}/get/custom_image_config", headers={"Authorization": f"Bearer {kv_token}"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                res = json.loads(resp.read().decode()).get("result")
                if res:
                    cfg = json.loads(res) if isinstance(res, str) else res
                    if isinstance(cfg, dict) and cfg.get("image_url"):
                        _memory_image_config = cfg
                        return cfg
        except Exception:
            pass

    # 2. Thử lấy từ file /tmp
    tmp_path = "/tmp/image_config.json"
    if os.path.exists(tmp_path):
        try:
            with open(tmp_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                if cfg.get("image_url"):
                    _memory_image_config = cfg
                    return cfg
        except Exception:
            pass

    # 3. Mặc định
    fallback = {
        "image_url": DEFAULT_IMAGE_URL,
        "mode": "proxy",
        "updated_at": "Mặc định"
    }
    _memory_image_config = fallback
    return fallback

def save_current_image_config(new_url, mode="proxy"):
    global _memory_image_config
    cfg = {
        "image_url": new_url.strip(),
        "mode": mode,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    _memory_image_config = cfg

    # 1. Lưu vào Vercel KV nếu có
    kv_url = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
    kv_token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    saved_to_kv = False
    if kv_url and kv_token:
        try:
            req = urllib.request.Request(
                f"{kv_url}/set/custom_image_config",
                data=json.dumps(cfg).encode(),
                headers={"Authorization": f"Bearer {kv_token}"}
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                saved_to_kv = True
        except Exception:
            pass

    # 2. Lưu vào /tmp
    try:
        with open("/tmp/image_config.json", "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except Exception:
        pass

    return cfg, saved_to_kv

def serve_fixed_image():
    """Trả về nội dung ảnh cố định theo URL tùy chỉnh đã cấu hình"""
    cfg = get_current_image_config()
    target_url = cfg.get("image_url", DEFAULT_IMAGE_URL)
    mode = cfg.get("mode", "proxy")

    if mode == "redirect":
        resp = redirect(target_url, code=302)
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0, s-maxage=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        resp.headers["Vercel-CDN-Cache-Control"] = "no-store"
        resp.headers["CDN-Cache-Control"] = "no-store"
        return resp

    try:
        req = urllib.request.Request(target_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            content = resp.read()
            content_type = resp.headers.get("Content-Type", "image/png")
            if len(content) > 4000000:
                return redirect(target_url, code=302)

            res = Response(content, mimetype=content_type)
            # Chống cache triệt để ở mọi tầng (Trình duyệt, Cloudflare, Vercel Edge CDN, App Mobile)
            res.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0, s-maxage=0"
            res.headers["Pragma"] = "no-cache"
            res.headers["Expires"] = "0"
            res.headers["Vercel-CDN-Cache-Control"] = "no-store"
            res.headers["CDN-Cache-Control"] = "no-store"
            res.headers["Surrogate-Control"] = "no-store"
            return res
    except Exception:
        resp = redirect(target_url, code=302)
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0, s-maxage=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

def handle_update_image():
    """API cập nhật link ảnh"""
    data = get_request_data()
    new_url = data.get("image_url") or data.get("new_image_url") or ""
    mode = data.get("mode", "proxy")

    if not new_url or not new_url.startswith("http"):
        return jsonify({"status": "error", "message": "Link ảnh không hợp lệ (phải bắt đầu bằng http:// hoặc https://)"}), 400

    cfg, is_kv = save_current_image_config(new_url, mode)
    return jsonify({
        "status": "success",
        "message": "Cập nhật link ảnh thành công!",
        "image_url": cfg["image_url"],
        "mode": cfg["mode"],
        "saved_to_kv": is_kv,
        "fixed_link": request.host_url.rstrip("/") + "/image.png"
    })

def render_image_tool_page():
    """Giao diện Web trực quan để quản lý link ảnh"""
    cfg = get_current_image_config()
    current_url = cfg.get("image_url", DEFAULT_IMAGE_URL)
    current_mode = cfg.get("mode", "proxy")
    storage_desc, is_kv = get_storage_info()
    fixed_link = request.host_url.rstrip("/") + "/image.png"

    html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quản Lý Link Ảnh Cố Định - Vercel Image Manager</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #090d16;
            --card-bg: rgba(22, 27, 46, 0.85);
            --border: rgba(99, 102, 241, 0.25);
            --primary: #6366f1;
            --primary-glow: rgba(99, 102, 241, 0.4);
            --accent: #06b6d4;
            --success: #10b981;
            --text: #f8fafc;
            --text-dim: #94a3b8;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Plus Jakarta Sans', sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 24px 16px;
            background-image: 
                radial-gradient(circle at 10% 20%, rgba(99, 102, 241, 0.18) 0%, transparent 40%),
                radial-gradient(circle at 90% 80%, rgba(6, 182, 212, 0.15) 0%, transparent 40%);
        }}
        .container {{
            max-width: 680px;
            width: 100%;
        }}
        .card {{
            background: var(--card-bg);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border);
            border-radius: 20px;
            padding: 32px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.5), 0 0 40px rgba(99,102,241,0.1);
        }}
        .header {{
            text-align: center;
            margin-bottom: 28px;
        }}
        .badge {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 14px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 600;
            background: rgba(99, 102, 241, 0.15);
            color: #818cf8;
            border: 1px solid rgba(99, 102, 241, 0.3);
            margin-bottom: 12px;
        }}
        .badge.active {{
            background: rgba(16, 185, 129, 0.15);
            color: #34d399;
            border-color: rgba(16, 185, 129, 0.3);
        }}
        h1 {{
            font-size: 26px;
            font-weight: 800;
            background: linear-gradient(135deg, #fff 30%, #a5b4fc 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
        }}
        p.subtitle {{
            color: var(--text-dim);
            font-size: 14px;
            line-height: 1.5;
        }}
        .section {{
            margin-bottom: 24px;
        }}
        .section-title {{
            font-size: 13px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--text-dim);
            margin-bottom: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .fixed-link-box {{
            background: rgba(10, 14, 28, 0.8);
            border: 1px solid rgba(99, 102, 241, 0.35);
            border-radius: 12px;
            padding: 12px 14px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .fixed-link-input {{
            background: transparent;
            border: none;
            color: #38bdf8;
            font-size: 14px;
            font-family: monospace;
            font-weight: 600;
            width: 100%;
            outline: none;
        }}
        .btn {{
            cursor: pointer;
            padding: 10px 18px;
            border-radius: 10px;
            font-weight: 600;
            font-size: 14px;
            font-family: inherit;
            border: none;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            white-space: nowrap;
        }}
        .btn-copy {{
            background: rgba(99, 102, 241, 0.2);
            color: #c7d2fe;
            border: 1px solid rgba(99, 102, 241, 0.4);
        }}
        .btn-copy:hover {{
            background: rgba(99, 102, 241, 0.4);
            color: #fff;
        }}
        .btn-view {{
            background: rgba(255, 255, 255, 0.08);
            color: #f1f5f9;
        }}
        .btn-view:hover {{
            background: rgba(255, 255, 255, 0.15);
        }}
        .input-group {{
            margin-bottom: 16px;
        }}
        .text-input {{
            width: 100%;
            background: rgba(10, 14, 28, 0.8);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 14px 16px;
            color: #fff;
            font-size: 14px;
            font-family: inherit;
            outline: none;
            transition: border-color 0.2s ease, box-shadow 0.2s ease;
        }}
        .text-input:focus {{
            border-color: var(--primary);
            box-shadow: 0 0 0 3px var(--primary-glow);
        }}
        .btn-primary {{
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
            color: #fff;
            font-size: 15px;
            font-weight: 700;
            box-shadow: 0 4px 16px rgba(99, 102, 241, 0.4);
        }}
        .btn-primary:hover {{
            opacity: 0.95;
            transform: translateY(-1px);
        }}
        .btn-primary:active {{
            transform: translateY(0);
        }}
        .preview-box {{
            margin-top: 24px;
            border-radius: 14px;
            overflow: hidden;
            border: 1px solid rgba(255, 255, 255, 0.1);
            background: rgba(0, 0, 0, 0.3);
            text-align: center;
            padding: 12px;
        }}
        .preview-img {{
            max-width: 100%;
            max-height: 280px;
            border-radius: 10px;
            object-fit: contain;
            display: block;
            margin: 0 auto;
        }}
        .alert {{
            padding: 12px 16px;
            border-radius: 10px;
            font-size: 14px;
            margin-bottom: 16px;
            display: none;
        }}
        .alert-success {{
            background: rgba(16, 185, 129, 0.15);
            border: 1px solid rgba(16, 185, 129, 0.4);
            color: #6ee7b7;
        }}
        .alert-error {{
            background: rgba(239, 68, 68, 0.15);
            border: 1px solid rgba(239, 68, 68, 0.4);
            color: #fca5a5;
        }}
        .footer-note {{
            font-size: 12px;
            color: var(--text-dim);
            margin-top: 20px;
            text-align: center;
            line-height: 1.6;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="header">
                <div class="badge {'active' if is_kv else ''}">
                    <span>{'⚡' if is_kv else '💾'}</span> {storage_desc}
                </div>
                <h1>Quản Lý Direct Link Ảnh Cố Định</h1>
                <p class="subtitle">Tùy biến nội dung ảnh bất cứ lúc nào mà không làm thay đổi link ảnh đầu ra cố định</p>
            </div>

            <div id="alertBox" class="alert"></div>

            {'<div style="background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 12px; padding: 14px; margin-bottom: 20px; font-size: 13px; color: #6ee7b7; line-height: 1.6;">✅ <b>Đã kết nối Vercel KV:</b> Ảnh được lưu vĩnh viễn trên đám mây toàn cầu. Mọi thay đổi sẽ có hiệu lực tức thì ở tất cả các thiết bị!</div>' if is_kv else '<div style="background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.35); border-radius: 12px; padding: 14px; margin-bottom: 20px; font-size: 13px; color: #fde68a; line-height: 1.6;"><div style="font-weight: 700; color: #fbbf24; margin-bottom: 4px;">⚠️ Chưa kết nối Vercel KV (Lý do bị quay về ảnh cũ):</div>Vì Vercel là Serverless (mỗi request có thể chạy ở 1 container khác nhau), nếu chưa bật KV thì ảnh bạn đổi chỉ lưu tạm trong container hiện tại. Khi thiết bị khác truy cập, Vercel mở container mới sẽ quay về ảnh cũ!<br><br>👉 <b>Cách bật Vercel KV để lưu vĩnh viễn (Miễn phí, 15 giây):</b><br>1. Vào <b>vercel.com</b> &rarr; mở project <b>aov-unlocked-main</b>.<br>2. Bấm tab <b>Storage</b> &rarr; <b>Create Database</b> &rarr; chọn <b>KV (Upstash)</b> &rarr; <b>Connect</b>.<br>3. Xong! Web này sẽ tự động chuyển sang lưu vĩnh viễn vĩnh viễn không mất!</div>'}

            <!-- MỤC 1: LINK ẢNH CỐ ĐỊNH -->
            <div class="section">
                <div class="section-title">
                    <span>📌 Direct Link Ảnh Đầu Ra Cố Định</span>
                    <span style="font-size: 11px; text-transform: none; color: #38bdf8;">Dùng link này cho Game / App</span>
                </div>
                <div class="fixed-link-box">
                    <input id="fixedLinkInput" class="fixed-link-input" type="text" readonly value="{fixed_link}">
                    <button class="btn btn-copy" onclick="copyFixedLink()">
                        <span id="copyIcon">📋</span> <span id="copyText">Sao chép</span>
                    </button>
                    <a href="{fixed_link}" target="_blank" class="btn btn-view" style="text-decoration: none;">
                        ↗ Mở ảnh
                    </a>
                </div>
            </div>

            <!-- MỤC 2: NHẬP LINK ẢNH TÙY CHỈNH MỚI -->
            <div class="section">
                <div class="section-title">
                    <span>🔄 Đổi Sang Link Ảnh Mới</span>
                </div>
                <div class="input-group">
                    <input id="newImageUrl" class="text-input" type="url" placeholder="Dán Direct Link ảnh mới vào đây (https://...)" value="{current_url}">
                </div>
                <div style="display: flex; gap: 16px; margin-bottom: 16px; font-size: 13px; color: var(--text-dim);">
                    <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
                        <input type="radio" name="imageMode" value="proxy" {'checked' if current_mode == 'proxy' else ''}>
                        Stream trực tiếp (Giữ nguyên domain cố định)
                    </label>
                    <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
                        <input type="radio" name="imageMode" value="redirect" {'checked' if current_mode == 'redirect' else ''}>
                        Chuyển hướng 302 (Tối ưu tốc độ)
                    </label>
                </div>
                <button class="btn btn-primary" onclick="updateImage()">
                    💾 Cập Nhật Link Ảnh Ngay
                </button>
            </div>

            <!-- MỤC 3: XEM TRƯỚC ẢNH HIỆN TẠI -->
            <div class="section" style="margin-bottom: 0;">
                <div class="section-title">
                    <span>🖼️ Ảnh Đang Hoạt Động (Live Preview)</span>
                </div>
                <div class="preview-box">
                    <img id="livePreviewImg" class="preview-img" src="{current_url}" alt="Preview" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'300\\' height=\\'150\\'><text x=\\'50%\\' y=\\'50%\\' fill=\\'%23999\\' text-anchor=\\'middle\\'>Kh%C3%B4ng t%E1%BA%A3i %C4%91%C6%B0%E1%BB%A3c %E1%BA%A3nh</text></svg>'">
                </div>
            </div>

            <div class="footer-note">
                💡 <b>Mẹo:</b> Khi bạn đổi ảnh mới, link <code>{fixed_link}</code> sẽ tự động cập nhật ngay lập tức mà không cần chỉnh sửa code trong ứng dụng của người dùng.
            </div>
        </div>
    </div>

    <script>
        function showAlert(msg, isSuccess) {{
            const box = document.getElementById('alertBox');
            box.style.display = 'block';
            box.className = 'alert ' + (isSuccess ? 'alert-success' : 'alert-error');
            box.textContent = msg;
            setTimeout(() => {{
                box.style.display = 'none';
            }}, 4000);
        }}

        function copyFixedLink() {{
            const copyText = document.getElementById("fixedLinkInput");
            copyText.select();
            copyText.setSelectionRange(0, 99999);
            navigator.clipboard.writeText(copyText.value).then(() => {{
                const copyBtnText = document.getElementById("copyText");
                const copyBtnIcon = document.getElementById("copyIcon");
                copyBtnText.textContent = "Đã chép!";
                copyBtnIcon.textContent = "✓";
                setTimeout(() => {{
                    copyBtnText.textContent = "Sao chép";
                    copyBtnIcon.textContent = "📋";
                }}, 2000);
            }});
        }}

        async function updateImage() {{
            const newUrl = document.getElementById('newImageUrl').value.trim();
            const mode = document.querySelector('input[name="imageMode"]:checked').value;

            if (!newUrl || !newUrl.startsWith('http')) {{
                showAlert('Vui lòng nhập link ảnh hợp lệ bắt đầu bằng http:// hoặc https://', false);
                return;
            }}

            try {{
                const res = await fetch('/api/update-image', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ image_url: newUrl, mode: mode }})
                }});

                const data = await res.json();
                if (res.ok && data.status === 'success') {{
                    showAlert('Cập nhật thành công! Link ảnh cố định đã chuyển sang ảnh mới.', true);
                    document.getElementById('livePreviewImg').src = newUrl;
                }} else {{
                    showAlert(data.message || 'Có lỗi xảy ra khi cập nhật.', false);
                }}
            }} catch (err) {{
                showAlert('Lỗi kết nối tới máy chủ: ' + err.message, false);
            }}
        }}
    </script>
</body>
</html>
"""
    return html

# ==========================================
# 3. ROUTING & CATCH-ALL TOÀN DIỆN
# ==========================================
def get_original_requested_url():
    """Lấy đúng đường dẫn người dùng gõ vào trình duyệt hoặc app gửi lên"""
    # 1. Thử lấy từ Vercel system header
    h_path = request.headers.get("x-invoke-path") or request.headers.get("x-matched-path")
    if h_path:
        return h_path.strip("/")
    # 2. Thử lấy từ REQUEST_URI (WSGI environment)
    req_uri = request.environ.get("REQUEST_URI") or request.environ.get("RAW_URI")
    if req_uri:
        parsed = urllib.parse.urlparse(req_uri)
        return parsed.path.strip("/")
    # 3. Thử lấy từ query param nếu có
    if request.args.get("path"):
        return request.args.get("path").strip("/")
    # 4. Fallback request.path
    return request.path.strip("/")

@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def catch_all(path=""):
    raw_path = get_original_requested_url()

    # 1. Endpoint xem ảnh cố định (ví dụ: /image.png, /live-image.png, /image.jpg)
    if any(raw_path.endswith(ext) for ext in ["image.png", "image.jpg", "image.jpeg", "live-image.png", "fixed-image.png"]) or raw_path == "image":
        return serve_fixed_image()

    # 2. Trang web quản lý ảnh
    if raw_path in ["image-tool", "image-manager", "admin-image", "image-config"]:
        if request.method == "POST":
            return handle_update_image()
        return render_image_tool_page()

    # 3. API cập nhật link ảnh
    if raw_path in ["api/update-image", "api/set-image"]:
        return handle_update_image()

    # 4. Endpoint Ping
    if raw_path == "ping":
        return "pong", 200

    # 5. Nếu là POST (hoặc URL là login): Xử lý login server game
    if request.method == "POST" or raw_path == "login":
        return handle_login()

    # 6. Trang chủ GET /
    return jsonify({
        "status": "online",
        "message": "AOV Key Server & Image Manager is running successfully!",
        "endpoints": {
            "login": "/login",
            "image_manager_web": "/image-tool",
            "fixed_image_url": "/image.png",
            "ping": "/ping"
        },
        "debug": {
            "raw_path": raw_path,
            "request_path": request.path,
            "headers": dict(request.headers)
        }
    })

# Fallback chống 404
@app.errorhandler(404)
def fallback_404(e):
    raw_path = get_original_requested_url()
    if any(raw_path.endswith(ext) for ext in ["image.png", "image.jpg", "image"]):
        return serve_fixed_image()
    if request.method == "POST":
        return handle_login()
    return jsonify({
        "status": "online",
        "message": "AOV Key Server & Image Manager is running successfully!",
        "endpoint": "/login"
    }), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
