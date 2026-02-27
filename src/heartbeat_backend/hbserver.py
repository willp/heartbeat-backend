#!/usr/bin/env python3 -u

import os
import sys
import socket
import json
import threading
import argparse

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
    from heartbeat_backend.models import HeartbeatEntry, current_epoch_int

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_address = (host_ip, port)
    server_socket.bind(server_address)

    print(f"UDP daemon listening on {host_ip}:{port}...")

    try:
        while True:
            data, client_address = server_socket.recvfrom(4096)
            ip_address = client_address[0]
            try:
                json_payload = json.loads(data)
                hbmesg = HeartbeatMessage(json_payload)

                entry, created = HeartbeatEntry.objects.update_or_create(
                    hostname=hbmesg.hostname,
                    app_name=hbmesg.app_name,
                    port=hbmesg.port,
                    task=hbmesg.task,
                    defaults={
                        'sender_ip': ip_address,
                        'interval': hbmesg.interval,
                        'alert_after': hbmesg.alert_after,
                        'version': hbmesg.version,
                        'final_report': hbmesg.final_report,
                        'sent_timestamp': hbmesg.sent_timestamp,
                        'received_timestamp': current_epoch_int(),
                    }
                )
            except json.JSONDecodeError:
                pass # Or log it
            except Exception as e:
                print(f"Database/Processing error: {e}")

    except Exception as e:
        print(f"UDP Server shutting down: {e}")
    finally:
        server_socket.close()


# --- EXECUTION BLOCK (Only runs if script is executed directly) ---

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Heartbeat Backend Server")
    parser.add_argument("--public", action="store_true", help="Bind HTTP to 0.0.0.0")
    parser.add_argument("--port", type=int, default=8333, help="Port to listen on")
    parser.add_argument("--production", action="store_true", help="Run using Waitress WSGI")
    parser.add_argument("--db", type=str, help="Absolute path to the SQLite database file")

    args, remaining_args = parser.parse_known_args()

    # Enforce Architectural Security Constraints
    if args.production and args.public:
        print("ERROR: --public cannot be used with --production.")
        sys.exit(1)

    # 1. Configure the Environment
    if args.db:
        os.environ['HEARTBEAT_DB_PATH'] = args.db
    
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'heartbeat_backend.settings')
    
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