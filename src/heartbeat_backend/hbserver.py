#!/usr/bin/python3 -u
#!/usr/bin/env python3 -u

import os
import sys
import socket
import json
import threading
import argparse

# --- DJANGO BOOTSTRAP ---
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'heartbeat_backend.settings')
import django
django.setup()

from heartbeat_backend.models import HeartbeatEntry, current_epoch_int
from django.core.management import execute_from_command_line
# ------------------------

class HeartbeatMessage:
    # ... (Keep your exact HeartbeatMessage class here) ...
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
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    server_address = (host_ip, port)
    server_socket.bind(server_address)

    print(f"UDP daemon listening on {host_ip}:{port}...")

    try:
        while True:
            data, client_address = server_socket.recvfrom(4096)
            ip_address = client_address[0]  # This is the sender's IP
            try:
                jlen = len(data)
                json_payload = json.loads(data)
                hbmesg = HeartbeatMessage(json_payload)

                # Django DB Interaction
                entry, created = HeartbeatEntry.objects.update_or_create(
                    hostname=hbmesg.hostname,
                    app_name=hbmesg.app_name,
                    port=hbmesg.port,
                    task=hbmesg.task,
                    defaults={
                        'sender_ip': ip_address,  # Store the IP here
                        'interval': hbmesg.interval,
                        'alert_after': hbmesg.alert_after,
                        'version': hbmesg.version,
                        'final_report': hbmesg.final_report,
                        'sent_timestamp': hbmesg.sent_timestamp,
                        'received_timestamp': current_epoch_int(),
                    }
                )
            except json.JSONDecodeError:
                print(f"Received non-JSON message from {client_address}")
            except Exception as e:
                print(f"Database/Processing error: {e}")

    except Exception as e:
        print(f"UDP Server shutting down: {e}")
    finally:
        server_socket.close()

if __name__ == "__main__":
    # 1. Parse command line arguments
    parser = argparse.ArgumentParser(description="Heartbeat Backend Server")
    parser.add_argument(
        "--public", 
        action="store_true", 
        help="Bind to 0.0.0.0 (all interfaces) instead of 127.0.0.1 (localhost)"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=8333, 
        help="Port to listen on for both UDP and TCP (default: 8333)"
    )
    
    # parse_known_args extracts our flags and ignores anything else
    args, remaining_args = parser.parse_known_args()
    
    # Determine the binding IP based on the flag
    host_ip = "0.0.0.0" if args.public else "127.0.0.1"

    # 2. Start the UDP daemon on a background thread
    udp_thread = threading.Thread(target=run_udp_server, args=(host_ip,args.port), daemon=True)
    udp_thread.start()

    # 3. Instruct Django to run the web server on the main thread
    print(f"Starting Django web server on {host_ip}:{args.port}...")
    
    # We explicitly build the arguments for Django so it never sees the --public flag
    runserver_args = [sys.argv[0], "runserver", f"{host_ip}:{args.port}", "--noreload"]
    execute_from_command_line(runserver_args)