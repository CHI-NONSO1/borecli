#!/usr/bin/env node

const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const executable =
    process.platform === "win32"
        ? path.join(__dirname, "bin", "bore.exe")
        : path.join(__dirname, "bin", "bore");

if (!fs.existsSync(executable)) {
    console.error(
        "BoreHook CLI is not installed correctly.\n" +
        "Please reinstall using:\n\n" +
        "    npm install -g borecli"
    );
    process.exit(1);
}

const child = spawn(
    executable,
    process.argv.slice(2),
    {
        stdio: "inherit",
    }
);

child.on("exit", (code) => {
    process.exit(code ?? 0);
});

child.on("error", (err) => {
    console.error("Failed to start BoreHook CLI.");
    console.error(err.message);
    process.exit(1);
});