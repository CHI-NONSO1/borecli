# BoreHook CLI (npm)

The official Node.js launcher for the **BoreHook CLI**.

This package automatically downloads the correct BoreHook executable for your operating system (Windows, macOS, or Linux) from the latest GitHub Release and makes it available as the `bore` command.

> No Python installation is required.

---

## Features

* 🚀 Expose localhost to the internet
* 🔒 Secure authenticated tunnels
* 🌍 Public HTTPS URLs
* 🔄 WebSocket-powered request forwarding
* ⏱️ Configurable login session duration
* 💻 Windows, macOS and Linux support

---

## Installation

Install globally with npm:

```bash
npm install -g borecli
```

Verify the installation:

```bash
bore --help
```

---

## Login

Authenticate your BoreHook account.

```bash
bore login
```

Specify a custom session duration:

```bash
bore login --time 15m
bore login --time 8h
bore login --time 7d
```

If no duration is supplied, the default session length is **1 hour**.

---

## Connect a Tunnel

Start forwarding requests to your local application.

```bash
bore connect
```

Example:

```text
Available Tunnels

[1] my-api
[2] webhook

Select tunnel: 1

🚀 Tunnel Connected

Tunnel ID: 99c2c16b-e78b-4790-bab8-93865118f91b
Subdomain: my-api
Public URL: https://my-api.borehook.com

Forwarding → http://127.0.0.1:3000

Press Ctrl+C to disconnect.
```

---

## Current User

Display the logged-in account.

```bash
bore whoami
```

Example:

```text
Logged in as: john@example.com
```

---

## Logout

Remove the local session.

```bash
bore logout
```

---

## Commands

| Command        | Description                           |
| -------------- | ------------------------------------- |
| `bore login`   | Authenticate your BoreHook account    |
| `bore connect` | Connect a tunnel                      |
| `bore whoami`  | Display the current logged-in account |
| `bore logout`  | Remove the local session              |

---

## Examples

Login with the default session:

```bash
bore login
```

Login for 30 minutes:

```bash
bore login --time 30m
```

Login for 8 hours:

```bash
bore login --time 8h
```

Connect a tunnel:

```bash
bore connect
```

Logout:

```bash
bore logout
```

---

## Requirements

* Windows 10+
* macOS 12+
* Linux
* Internet connection

---

## Documentation

Website: https://borehook.com

---

## Support

Website: https://borehook.com

Email: [support@borehook.com](mailto:support@borehook.com)

---

## License

MIT License.

---

Built with ❤️ by the BoreHook Team.
