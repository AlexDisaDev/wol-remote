#!/usr/bin/env python3
"""
Wake-on-LAN Web App — con login Google OAuth
"""
import json, os, socket, subprocess, platform
import ProxyFix
from datetime import datetime
from functools import wraps
from flask import Flask, jsonify, request, render_template, redirect, url_for, session
from flask_cors import CORS
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
CORS(app)

DATA_FILE = "data.json"

# ─── OAuth Google ──────────────────────────────────────────────────────────────
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return jsonify({"error": "No autenticado", "redirect": "/login"}), 401
        return f(*args, **kwargs)
    return decorated

def current_user():
    return session.get('user', {})

def user_email():
    return current_user().get('email', 'anonymous')


# ─── Persistencia por usuario ──────────────────────────────────────────────────
def load(email=None):
    email = email or user_email()
    if not os.path.exists(DATA_FILE):
        return {"routers": [], "devices": []}
    with open(DATA_FILE) as f:
        all_data = json.load(f)
    return all_data.get(email, {"routers": [], "devices": []})

def save(data, email=None):
    email = email or user_email()
    all_data = {}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            all_data = json.load(f)
    all_data[email] = data
    with open(DATA_FILE, "w") as f:
        json.dump(all_data, f, indent=2)

def new_id():
    return str(int(datetime.now().timestamp() * 1000))


# ─── WOL ──────────────────────────────────────────────────────────────────────
def build_magic_packet(mac: str) -> bytes:
    clean = mac.replace(":", "").replace("-", "").replace(".", "").upper()
    if len(clean) != 12:
        raise ValueError(f"MAC inválida: {mac}")
    return b'\xff' * 6 + bytes.fromhex(clean) * 16

def send_wol(mac: str, target_ip: str, port: int = 9) -> dict:
    packet = build_magic_packet(mac)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(5)
    try:
        sock.sendto(packet, (target_ip, port))
        return {"sent": True, "target": f"{target_ip}:{port}", "bytes": len(packet)}
    finally:
        sock.close()

def ping_host(ip: str, timeout: int = 2) -> bool:
    system = platform.system().lower()
    cmd = ["ping", "-n" if system == "windows" else "-c", "1",
           "-w" if system == "windows" else "-W",
           str(timeout * 1000 if system == "windows" else timeout), ip]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout + 2)
        return r.returncode == 0
    except Exception:
        return False


# ─── Auth routes ──────────────────────────────────────────────────────────────
@app.route("/login")
def login_page():
    if 'user' in session:
        return redirect("/")
    return render_template("login.html")

@app.route("/auth/google")
def auth_google():
    redirect_uri = url_for("auth_callback", _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route("/auth/callback")
def auth_callback():
    token = google.authorize_access_token()
    userinfo = token.get('userinfo')
    session['user'] = {
        'email': userinfo['email'],
        'name': userinfo.get('name', userinfo['email']),
        'picture': userinfo.get('picture', ''),
    }
    return redirect("/")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/api/me")
def me():
    if 'user' not in session:
        return jsonify({"authenticated": False})
    return jsonify({"authenticated": True, **current_user()})


# ─── Página principal ──────────────────────────────────────────────────────────
@app.route("/")
def index():
    if 'user' not in session:
        return redirect("/login")
    return render_template("index.html")


# ─── API Routers ───────────────────────────────────────────────────────────────
@app.route("/api/routers", methods=["GET"])
@login_required
def get_routers():
    return jsonify(load()["routers"])

@app.route("/api/routers", methods=["POST"])
@login_required
def create_router():
    b = request.get_json()
    name      = b.get("name", "").strip()
    public_ip = b.get("public_ip", "").strip()
    port      = int(b.get("port", 9))
    notes     = b.get("notes", "").strip()
    if not name or not public_ip:
        return jsonify({"error": "Nombre e IP pública son obligatorios"}), 400
    data = load()
    router = {"id": new_id(), "name": name, "public_ip": public_ip,
              "port": port, "notes": notes, "created_at": datetime.now().isoformat()}
    data["routers"].append(router)
    save(data)
    return jsonify(router), 201

@app.route("/api/routers/<rid>", methods=["PUT"])
@login_required
def update_router(rid):
    b = request.get_json()
    data = load()
    for r in data["routers"]:
        if r["id"] == rid:
            for k, v in b.items():
                if k not in ("id", "created_at"): r[k] = v
            save(data); return jsonify(r)
    return jsonify({"error": "No encontrado"}), 404

@app.route("/api/routers/<rid>", methods=["DELETE"])
@login_required
def delete_router(rid):
    data = load()
    data["routers"] = [r for r in data["routers"] if r["id"] != rid]
    save(data); return jsonify({"ok": True})


# ─── API Devices ───────────────────────────────────────────────────────────────
@app.route("/api/devices", methods=["GET"])
@login_required
def get_devices():
    return jsonify(load()["devices"])

@app.route("/api/devices", methods=["POST"])
@login_required
def create_device():
    b = request.get_json()
    name      = b.get("name", "").strip()
    mac       = b.get("mac", "").strip()
    router_id = b.get("router_id", "").strip()
    local_ip  = b.get("local_ip", "").strip()
    desc      = b.get("description", "").strip()
    if not name or not mac:
        return jsonify({"error": "Nombre y MAC son obligatorios"}), 400
    clean = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(clean) != 12:
        return jsonify({"error": "MAC inválida"}), 400
    data = load()
    device = {"id": new_id(), "name": name, "mac": mac.upper(),
              "router_id": router_id, "local_ip": local_ip, "description": desc,
              "created_at": datetime.now().isoformat(), "last_wake": None, "last_status": None}
    data["devices"].append(device)
    save(data); return jsonify(device), 201

@app.route("/api/devices/<did>", methods=["PUT"])
@login_required
def update_device(did):
    b = request.get_json()
    data = load()
    for d in data["devices"]:
        if d["id"] == did:
            for k, v in b.items():
                if k not in ("id", "created_at"): d[k] = v
            save(data); return jsonify(d)
    return jsonify({"error": "No encontrado"}), 404

@app.route("/api/devices/<did>", methods=["DELETE"])
@login_required
def delete_device(did):
    data = load()
    data["devices"] = [d for d in data["devices"] if d["id"] != did]
    save(data); return jsonify({"ok": True})


# ─── Wake ──────────────────────────────────────────────────────────────────────
@app.route("/api/wake/<did>", methods=["POST"])
@login_required
def wake_device(did):
    data = load()
    device = next((d for d in data["devices"] if d["id"] == did), None)
    if not device:
        return jsonify({"error": "Dispositivo no encontrado"}), 404
    router = next((r for r in data["routers"] if r["id"] == device.get("router_id")), None)
    target_ip = router["public_ip"] if router else "255.255.255.255"
    port = router["port"] if router else 9
    try:
        result = send_wol(device["mac"], target_ip, port)
        device["last_wake"] = datetime.now().isoformat()
        device["last_status"] = "sent"
        save(data)
        return jsonify({"success": True, "message": f"Magic packet enviado a {device['name']}",
                        "detail": f"{result['bytes']} bytes UDP → {result['target']}",
                        "router": router["name"] if router else "Sin router"})
    except Exception as e:
        device["last_status"] = "error"
        save(data)
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/ping/<did>", methods=["GET"])
@login_required
def ping_device(did):
    data = load()
    device = next((d for d in data["devices"] if d["id"] == did), None)
    if not device:
        return jsonify({"error": "No encontrado"}), 404
    ip = device.get("local_ip", "").strip()
    if not ip:
        return jsonify({"reachable": None, "message": "IP local no configurada"})
    return jsonify({"reachable": ping_host(ip), "ip": ip})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
