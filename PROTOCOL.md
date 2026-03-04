# UDP packet: JSON and Binary Protocol

## JSON Packet:

## Binary Packet for Encrypted Messages

| Offset | Size (Bytes) | Component | Description |
| --- | --- | --- | --- |
| 0 | 1 | Magic Byte | "0xDB (Signals a secure binary packet |  not JSON)" |
| 1 | 1 | Version | 0x01 (Protocol version) |
| 2 | 4 | Key ID | 32-bit unsigned integer (Identifies which AES key the server should use to decrypt) |
| 6 | 12 | Nonce | Random IV required for AES-GCM. Must be unique per packet. |
| 18 | Variable | Ciphertext | The encrypted JSON payload. |
| 18+N | 16 | Auth Tag | The AES-GCM cryptographic signature. |
| Tail | 4 | Checksum | A fast CRC32 hash of the entire preceding packet. |

For the tail checksum, we use zlib.crc32. It is built directly into the Python standard library, written entirely in C, and operates blisteringly fast. It is perfect for dropping packets corrupted by network noise before we waste CPU cycles attempting cryptographic decryption.
