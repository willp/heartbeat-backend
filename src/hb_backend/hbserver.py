#!/usr/bin/env python3 -u

import os
import sys
import socket
import json
import threading
import argparse
import struct
import zlib
import base64

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
# --- SAFE, IMPORTABLE CLASSES & FUNCTIONS ---

class HeartbeatMessage:
    def __init__(self, metadata):
        self.hostname = metadata.get("h")
        self.app_name = metadata.get("n")
        self.port = metadata.get("p")
        self.task = metadata.get("t")
        self.interval = metadata.get("i")
        self.alert_after = metadata.get("!")
        self.sent_timestamp = metadata.get("@")
        self.version = metadata.get("v")
        self.final_report = metadata.get("f")

    def __repr__(self):
        attrs = {k: v for k, v in self.__dict__.items() if v is not None}
        return f"{self.__class__.__name__}({attrs})"

    @classmethod
    def from_json(cls, json_str):
        metadata = json.loads(json_str)
        return cls(metadata)



def run_udp_server(host_ip, port):
    """Runs the UDP listener daemon."""
    # LAZY IMPORT: We import the Django models inside the function.
    # This guarantees Django is fully booted before we try to load the models,
    # preventing errors if another script imports this module.
    from hb_backend.models import HeartbeatEntry, current_epoch_int

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_address = (host_ip, port)
    server_socket.bind(server_address)

    print(f"UDP daemon listening on {host_ip}:{port}...")

    try:
        while True:
            data, client_address = server_socket.recvfrom(4096)
            ip_address = client_address[0]
            
            if not data: continue

            json_payload = None
            is_secure_payload = False

            # --- ROUTE 1: THE BINARY ENCRYPTED PACKET ---
            if data[0] == 0xDB:
                try:
                    if len(data) < 38: continue
                    
                    packet_crc = struct.unpack(">I", data[-4:])[0]
                    if packet_crc != (zlib.crc32(data[:-4]) & 0xFFFFFFFF):
                        continue

                    version = data[1]
                    if version != 1: continue

                    key_id = struct.unpack(">I", data[2:6])[0]
                    nonce = data[6:18]
                    encrypted_payload = data[18:-4] 

                    from hb_backend.models import ClientKey, AlertState
                    try:
                        client_key = ClientKey.objects.get(id=key_id, is_revoked=False)
                    except ClientKey.DoesNotExist:
                        continue

                    # Decrypt (With Fail-Safe Overlap)
                    try:
                        aesgcm = AESGCM(base64.b64decode(client_key.aes_secret))
                        decrypted_bytes = aesgcm.decrypt(nonce, encrypted_payload, associated_data=None)
                        json_payload = json.loads(decrypted_bytes.decode('utf-8'))
                        is_secure_payload = True

                        # --- NEW: Update the last_used_at timestamp ---
                        from hb_backend.models import current_epoch_int
                        ClientKey.objects.filter(pk=client_key.pk).update(last_used_at=current_epoch_int())

                    except Exception:
                        if client_key.previous_aes_secret:
                            try:
                                aesgcm_prev = AESGCM(base64.b64decode(client_key.previous_aes_secret))
                                decrypted_bytes = aesgcm_prev.decrypt(nonce, encrypted_payload, associated_data=None)
                                json_payload = json.loads(decrypted_bytes.decode('utf-8'))
                                is_secure_payload = True

                                # --- NEW: Update the last_used_at timestamp ---
                                from hb_backend.models import current_epoch_int
                                ClientKey.objects.filter(pk=client_key.pk).update(last_used_at=current_epoch_int())

                            except Exception:
                                continue
                        else:
                            continue
                except Exception as e:
                    print(f"Binary parse error: {e}")
                    continue

            # --- ROUTE 2: THE LEGACY CLEARTEXT JSON PACKET ---
            elif data[0] == 123: # ASCII '{'
                try:
                    json_payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
            
            # --- COMMON DATABASE INGESTION WITH SECURITY RULES ---
            if json_payload:
                try:
                    hbmesg = HeartbeatMessage(json_payload)
                    from hb_backend.models import AlertState # Lazy import

                    # 1. Fetch the existing entry to check security rules
                    entry = HeartbeatEntry.objects.filter(
                        hostname=hbmesg.hostname, app_name=hbmesg.app_name,
                        port=hbmesg.port, task=hbmesg.task
                    ).first()

                    # 2. Strict Mode Check
                    if entry and not is_secure_payload:
                        if entry.enforce_encryption:
                            print(f"Dropped unencrypted fallback from {ip_address} (Strict Mode Enforced)")
                            continue

                    # 3. Prepare the update payload
                    defaults = {
                        'sender_ip': ip_address,
                        'interval': hbmesg.interval,
                        'alert_after': hbmesg.alert_after,
                        'version': hbmesg.version,
                        'final_report': hbmesg.final_report,
                        'sent_timestamp': hbmesg.sent_timestamp,
                        'received_timestamp': current_epoch_int(),
                    }

                    # 4. Handle State Transitions
                    if is_secure_payload:
                        defaults['is_encrypted'] = True
                        if entry and entry.alert_state == AlertState.DEGRADED:
                            defaults['alert_state'] = AlertState.NORMAL # Self-healing!
                    elif entry and entry.is_encrypted:
                        defaults['alert_state'] = AlertState.DEGRADED # Fallback triggered!

                    # 5. Commit
                    HeartbeatEntry.objects.update_or_create(
                        hostname=hbmesg.hostname,
                        app_name=hbmesg.app_name,
                        port=hbmesg.port,
                        task=hbmesg.task,
                        defaults=defaults
                    )
                except Exception as e:
                    print(f"Database/Processing error: {e}")

    except Exception as e:
        print(f"UDP Server shutting down: {e}")
    finally:
        server_socket.close()


# --- EXECUTION BLOCK (Only runs if script is executed directly) ---

def main() -> None:
    parser = argparse.ArgumentParser(description="Heartbeat Backend Server")
    parser.add_argument("--public", action="store_true", help="Bind HTTP to 0.0.0.0")
    parser.add_argument("--port", type=int, default=8333, help="Port to listen on")
    parser.add_argument("--production", action="store_true", help="Run using Waitress WSGI")
    parser.add_argument("--db", type=str, help="Absolute path to the SQLite database file")

    args, remaining_args = parser.parse_known_args()

    def is_docker():
        """Returns True if explicitly told we are in a container."""
        return os.environ.get('RUNNING_IN_CONTAINER') == 'true'

    # Existing Safety Check
    print(f"Checking safety...")
    if args.production and args.public:
        if not is_docker():
            print("ERROR: --public cannot be used with --production on a host machine.")
            print("This is a safety guardrail to prevent accidental network exposure.")
            sys.exit(1)
        else:
            # We are in Docker, so this is expected and allowed.
            print("🐳 Docker environment detected. Enabling public production binding.")

    host_ip = "0.0.0.0" if args.public else "127.0.0.1"

    # 1. Configure the Environment
    if args.db:
        os.environ['HEARTBEAT_DB_PATH'] = args.db
    
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hb_backend.settings')
    
    # 2. Boot Django
    import django
    django.setup()
    
    # 3. Import Django execution utilities
    from django.core.management import execute_from_command_line

    host_ip = "0.0.0.0" if args.public else "127.0.0.1"

    # 4. Start the UDP daemon
    udp_thread = threading.Thread(target=run_udp_server, args=("0.0.0.0", args.port), daemon=True)
    udp_thread.start()

    # 5. Start the Web Server
    if args.production:
        try:
            import waitress
            from django.core.wsgi import get_wsgi_application
        except ImportError:
            print("ERROR: Waitress is not installed.")
            sys.exit(1)
            
        print(f"Starting Waitress securely on {host_ip}:{args.port}...")
        application = get_wsgi_application()
        waitress.serve(application, host=host_ip, port=args.port)
    else:
        print(f"Starting Django development server on {host_ip}:{args.port}...")
        runserver_args = [sys.argv[0], "runserver", f"{host_ip}:{args.port}", "--noreload"]
        execute_from_command_line(runserver_args)


if __name__ == "__main__":
    main()