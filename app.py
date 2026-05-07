#!/usr/bin/env python3
"""
Wake-on-LAN Web App
Ejecuta en una máquina de tu red local y accede desde cualquier lugar.
"""

import json
import os
import socket
import struct
import subprocess
import platform
from datetime import datetime
from flask import Flask, jsonify, request, render_template, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DATA_FILE = "devices.json"


# ─── Persistencia ────────────────────────────────────────────────────────────

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"devices": []}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ─── WOL ─────────────────────────────────────────────────────────────────────

def build_magic_packet(mac: str) -> bytes:
    """Construye el magic packet WOL: 6×FF + 16×MAC"""
    clean = mac.replace(":", "").replace("-", "").replace(".", "").upper()
    if len(clean) != 12:
        raise ValueError(f"MAC inválida: {mac}")
    mac_bytes = bytes.fromhex(clean)
    return b'\xff' * 6 + mac_bytes * 16


def send_wol(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> dict:
    packet = build_magic_packet(mac)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(3)
    try:
        sock.connect((broadcast, port))
        sock.send(packet)
        # Enviar también al broadcast de subred si se proporcionó
        if broadcast != "255.255.255.255":
            sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock2.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock2.sendto(packet, ("255.255.255.255", port))
            sock2.close()
        return {"sent": True, "target": f"{broadcast}:{port}", "bytes": len(packet)}
    finally:
        sock.close()


def ping_host(ip: str, timeout: int = 2) -> bool:
    """Hace ping al host. Funciona en Windows y Linux/macOS."""
    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", "1", "-w", str(timeout * 1000), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", str(timeout), ip]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout + 2)
        return result.returncode == 0
    except Exception:
        return False


# ─── API Routes ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/devices", methods=["GET"])
def get_devices():
    data = load_data()
    return jsonify(data["devices"])


@app.route("/api/devices", methods=["POST"])
def create_device():
    body = request.get_json()
    name = body.get("name", "").strip()
    mac = body.get("mac", "").strip()
    broadcast = body.get("broadcast", "255.255.255.255").strip()
    port = int(body.get("port", 9))
    description = body.get("description", "").strip()

    if not name or not mac:
        return jsonify({"error": "Nombre y MAC son obligatorios"}), 400

    # Validar MAC
    clean = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(clean) != 12 or not all(c in "0123456789abcdefABCDEF" for c in clean):
        return jsonify({"error": "Dirección MAC inválida"}), 400

    data = load_data()
    device = {
        "id": str(int(datetime.now().timestamp() * 1000)),
        "name": name,
        "mac": mac.upper(),
        "broadcast": broadcast,
        "port": port,
        "description": description,
        "created_at": datetime.now().isoformat(),
        "last_wake": None,
        "last_status": None,
    }
    data["devices"].append(device)
    save_data(data)
    return jsonify(device), 201


@app.route("/api/devices/<device_id>", methods=["PUT"])
def update_device(device_id):
    body = request.get_json()
    data = load_data()
    for d in data["devices"]:
        if d["id"] == device_id:
            d.update({k: v for k, v in body.items() if k not in ("id", "created_at")})
            save_data(data)
            return jsonify(d)
    return jsonify({"error": "Dispositivo no encontrado"}), 404


@app.route("/api/devices/<device_id>", methods=["DELETE"])
def delete_device(device_id):
    data = load_data()
    data["devices"] = [d for d in data["devices"] if d["id"] != device_id]
    save_data(data)
    return jsonify({"ok": True})


@app.route("/api/wake/<device_id>", methods=["POST"])
def wake_device(device_id):
    data = load_data()
    device = next((d for d in data["devices"] if d["id"] == device_id), None)
    if not device:
        return jsonify({"error": "Dispositivo no encontrado"}), 404

    try:
        result = send_wol(device["mac"], device["broadcast"], device["port"])
        device["last_wake"] = datetime.now().isoformat()
        device["last_status"] = "sent"
        save_data(data)
        return jsonify({
            "success": True,
            "message": f"Magic packet enviado a {device['name']}",
            "detail": f"{result['bytes']} bytes → {result['target']}",
        })
    except Exception as e:
        device["last_status"] = "error"
        save_data(data)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/ping/<device_id>", methods=["GET"])
def ping_device(device_id):
    data = load_data()
    device = next((d for d in data["devices"] if d["id"] == device_id), None)
    if not device:
        return jsonify({"error": "Dispositivo no encontrado"}), 404

    # Intentar extraer IP del campo broadcast o usar la broadcast address
    # El ping se hace a la IP local del dispositivo si se configuró
    ip = device.get("local_ip", "").strip()
    if not ip:
        return jsonify({"reachable": None, "message": "IP local no configurada"})

    reachable = ping_host(ip)
    return jsonify({"reachable": reachable, "ip": ip})


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    print(f"\n🌐 WOL App corriendo en http://{host}:{port}")
    print(f"   Accede desde tu red local o desde internet (con port forwarding)\n")
    app.run(host=host, port=port, debug=debug)
