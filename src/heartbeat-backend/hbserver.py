#!/usr/bin/python3 -u

import socket
import json

class HeartbeatMessage:
    def __init__(self, metadata):
        # unique identifiers
        self.hostname = metadata.get('h')
        self.app_name = metadata.get('n')
        self.port = metadata.get('p')
        self.task = metadata.get('t')
        #
        self.interval = metadata.get('i')
        self.alert_after = metadata.get('!')
        self.sent_timestamp = metadata.get('@')
        self.version = metadata.get('v')
        self.final_report = metadata.get('f')

    def __repr__(self):
        attrs = {k: v for k, v in self.__dict__.items() if v is not None}
        return f'{self.__class__.__name__}({attrs})'

    @classmethod
    def from_json(cls, json_str):
        metadata = json.loads(json_str)
        return cls(metadata)

# Create a UDP socket object
server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Bind the socket to the specified IP address and port
server_address = ('localhost', 3333)
server_socket.bind(server_address)

print('UDP server listening on port 3333')

while True:
    # Receive data from client
    data, client_address = server_socket.recvfrom(1024)

    try:
        # Decode JSON payload if possible
        jlen = len(data)
        json_payload = json.loads(data)
        hbmesg = HeartbeatMessage(json_payload)
        print(f'Received {jlen} bytes, JSON message from {client_address}: {json_payload}')
        print(f"As an hbmesg object: {hbmesg}")
    except json.JSONDecodeError:
        print(f'Received {jlen} bytes, non-JSON message from {client_address}: {data.decode("utf-8")}')

server_socket.close()
