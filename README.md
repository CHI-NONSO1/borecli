# BoreHook CLI

The official command-line interface for **BoreHook** — securely expose your localhost to the internet, test webhooks, and debug HTTP requests without deploying your application.

## Features

* 🚀 Expose localhost over HTTPS
* 🔐 Secure authenticated tunnels
* 🔄 Persistent tunnel management
* 📡 WebSocket-powered request forwarding
* ⏱️ Configurable login session duration
* 💻 Cross-platform (Windows, macOS, Linux)

---

## Installation

### Python (PyPI)

```bash
pip install borecli
```

### Node.js (npm)

```bash
npm install -g borecli
```

---

## Login

Authenticate your BoreHook account.

```bash
bore login
```

Specify a custom session duration:

```bash
bore login --time 30m
```

```bash
bore login --time 8h
```

```bash
bore login --time 7d
```

If no duration is specified, the default session length is **1 hour**.

Supported time units:

| Example | Meaning    |
| ------- | ---------- |
| `30m`   | 30 Minutes |
| `2h`    | 2 Hours    |
| `7d`    | 7 Days     |

---

## Check Current User

```bash
bore whoami
```

Example:

```text
Logged in as: john@example.com
```

---

## Logout

```bash
bore logout
```

---

## Connect a Tunnel

Start forwarding traffic to your local application.

```bash
bore connect
```

You'll be prompted to select one of your configured tunnels.

Example:

```text
Available Tunnels

[1] my-api
[2] webhook
[3] development

Select tunnel:
```

After connecting:

```text
🚀 Tunnel Connected

Tunnel ID: 99c2c16b-e78b-4790-bab8-93865118f91b
Subdomain: webhook
Public URL: https://webhook.borehook.com

Forwarding → http://127.0.0.1:8000

Press Ctrl+C to disconnect.
```

---

## Commands

| Command        | Description                           |
| -------------- | ------------------------------------- |
| `bore login`   | Authenticate your account             |
| `bore connect` | Connect to a tunnel                   |
| `bore whoami`  | Display the current logged-in account |
| `bore logout`  | Remove the local session              |

---

## Examples

Login for one hour (default):

```bash
bore login
```

Login for 15 minutes:

```bash
bore login --time 15m
```

Login for 8 hours:

```bash
bore login --time 8h
```

Connect to a tunnel:

```bash
bore connect
```

Logout:

```bash
bore logout
```

---

## Requirements

* Windows
* macOS
* Linux

Internet connection required.

---

## Documentation

Visit **https://borehook.com** for documentation, tutorials, and guides.

---

## Support

* Website: https://borehook.com
* Email: [support@borehook.com](mailto:support@borehook.com)

---

## License

MIT License.

---

Built with ❤️ by the BoreHook team.
