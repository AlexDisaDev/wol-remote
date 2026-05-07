# 🌐 WOL Remote — Wake-on-LAN desde cualquier lugar

App web para encender tus PCs remotamente mediante **UDP Magic Packet**.

## ¿Cómo funciona?

Esta app corre en una máquina **dentro de tu red local** (un PC siempre encendido, 
Raspberry Pi, NAS, etc.). Al enviar el magic packet desde ahí, el paquete llega 
directamente a la red local y despierta el PC objetivo.

Tú accedes a la app desde internet (con port forwarding HTTP apuntando a esa máquina).

```
Internet → Tu router → Esta app (HTTP:5000) → UDP broadcast → PC objetivo
```

## Requisitos

- Python 3.8+
- Una máquina siempre encendida en tu red (RPi, NAS, otro PC...)
- Port forwarding en el router: **TCP puerto 5000** → IP de la máquina con la app

## Instalación

```bash
# 1. Clona el repositorio
git clone https://github.com/TU_USUARIO/wol-remote.git
cd wol-remote

# 2. Instala dependencias
pip install -r requirements.txt

# 3. Ejecuta la app
python app.py
```

Accede en: `http://localhost:5000`  
Desde fuera: `http://TU_IP_PUBLICA:5000`

## Configuración del router

1. **Port forwarding**: TCP 5000 → IP_de_tu_Raspberry_o_PC_siempre_encendido
2. Para WOL también: UDP 9 → 192.168.X.255 (broadcast de tu subred) + ARP estático del PC objetivo

## Variables de entorno

```bash
HOST=0.0.0.0   # interfaz (por defecto 0.0.0.0)
PORT=5000       # puerto HTTP (por defecto 5000)
DEBUG=false     # modo debug
```

## Broadcast address

- `255.255.255.255` → broadcast global (puede no funcionar fuera de la subred)
- `192.168.1.255` → broadcast de subred /24 ← **recomendado**

## Seguridad

⚠️ Esta app no tiene autenticación. Para uso en internet, considera:
- Ponerla detrás de una VPN
- Añadir autenticación HTTP básica con nginx
- Limitar el acceso por IP en el router
