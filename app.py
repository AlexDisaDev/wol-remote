#!/usr/bin/env python3
"""
Wake-on-LAN Web App
Hospedada en Railway/cloud — envía magic packets a través del router de casa.
"""

import json, os, socket, subprocess, platform
from datetime import datetime
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DATA_FILE = "data.json"


# ─── Persistencia ─────────────────────────────────────────────────────────────

def load():
    if not os.path.exists(DATA_FILE):
        return {"routers": [], "devices": []}
    with open(DATA_FILE) as f:
        return json.load(f)

def save(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def new_id():
    return str(int(datetime.now().timestamp() * 1000))


# ─── WOL ──────────────────────────────────────────────────────────────────────

def build_magic_packet(mac: str) -> bytes:
    clean = mac.replace(":", "").replace("-", "").replace(".", "").upper()
    if len(clean) != 12:
        raise ValueError(f"MAC inválida: {mac}")
    mac_bytes = bytes.fromhex(clean)
    return b'\xff' * 6 + mac_bytes * 16

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


# ─── Página principal ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ─── API Routers ──────────────────────────────────────────────────────────────

@app.route("/api/routers", methods=["GET"])
def get_routers():
    return jsonify(load()["routers"])

@app.route("/api/routers", methods=["POST"])
def create_router():
    b = request.get_json()
    name      = b.get("name", "").strip()
    public_ip = b.get("public_ip", "").strip()
    port      = int(b.get("port", 9))
    notes     = b.get("notes", "").strip()

    if not name or not public_ip:
        return jsonify({"error": "Nombre e IP pública son obligatorios"}), 400

    data = load()
    router = {
        "id": new_id(),
        "name": name,
        "public_ip": public_ip,
        "port": port,
        "notes": notes,
        "created_at": datetime.now().isoformat(),
    }
    data["routers"].append(router)
    save(data)
    return jsonify(router), 201

@app.route("/api/routers/<rid>", methods=["PUT"])
def update_router(rid):
    b = request.get_json()
    data = load()
    for r in data["routers"]:
        if r["id"] == rid:
            for k, v in b.items():
                if k not in ("id", "created_at"):
                    r[k] = v
            save(data)
            return jsonify(r)
    return jsonify({"error": "Router no encontrado"}), 404

@app.route("/api/routers/<rid>", methods=["DELETE"])
def delete_router(rid):
    data = load()
    data["routers"] = [r for r in data["routers"] if r["id"] != rid]
    save(data)
    return jsonify({"ok": True})


# ─── API Devices ──────────────────────────────────────────────────────────────

@app.route("/api/devices", methods=["GET"])
def get_devices():
    return jsonify(load()["devices"])

@app.route("/api/devices", methods=["POST"])
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
    device = {
        "id": new_id(),
        "name": name,
        "mac": mac.upper(),
        "router_id": router_id,
        "local_ip": local_ip,
        "description": desc,
        "created_at": datetime.now().isoformat(),
        "last_wake": None,
        "last_status": None,
    }
    data["devices"].append(device)
    save(data)
    return jsonify(device), 201

@app.route("/api/devices/<did>", methods=["PUT"])
def update_device(did):
    b = request.get_json()
    data = load()
    for d in data["devices"]:
        if d["id"] == did:
            for k, v in b.items():
                if k not in ("id", "created_at"):
                    d[k] = v
            save(data)
            return jsonify(d)
    return jsonify({"error": "Dispositivo no encontrado"}), 404

@app.route("/api/devices/<did>", methods=["DELETE"])
def delete_device(did):
    data = load()
    data["devices"] = [d for d in data["devices"] if d["id"] != did]
    save(data)
    return jsonify({"ok": True})


# ─── Wake ─────────────────────────────────────────────────────────────────────

@app.route("/api/wake/<did>", methods=["POST"])
def wake_device(did):
    data = load()
    device = next((d for d in data["devices"] if d["id"] == did), None)
    if not device:
        return jsonify({"error": "Dispositivo no encontrado"}), 404

    router = next((r for r in data["routers"] if r["id"] == device.get("router_id")), None)

    if router:
        target_ip = router["public_ip"]
        port = router["port"]
    else:
        target_ip = "255.255.255.255"
        port = 9

    try:
        result = send_wol(device["mac"], target_ip, port)
        device["last_wake"] = datetime.now().isoformat()
        device["last_status"] = "sent"
        save(data)
        return jsonify({
            "success": True,
            "message": f"Magic packet enviado a {device['name']}",
            "detail": f"{result['bytes']} bytes UDP → {result['target']}",
            "router": router["name"] if router else "Sin router",
        })
    except Exception as e:
        device["last_status"] = "error"
        save(data)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/ping/<did>", methods=["GET"])
def ping_device(did):
    data = load()
    device = next((d for d in data["devices"] if d["id"] == did), None)
    if not device:
        return jsonify({"error": "Dispositivo no encontrado"}), 404
    ip = device.get("local_ip", "").strip()
    if not ip:
        return jsonify({"reachable": None, "message": "IP local no configurada"})
    return jsonify({"reachable": ping_host(ip), "ip": ip})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    print(f"\n WOL App → http://{host}:{port}\n")
    app.run(host=host, port=port, debug=debug)
