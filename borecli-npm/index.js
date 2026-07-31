#!/usr/bin/env node

const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const executableName =
    process.platform === "win32"
        ? "bore.exe"
        : "bore";

function findExecutable(dir) {

    const entries = fs.readdirSync(dir, {
        withFileTypes: true,
    });

    for (const entry of entries) {

        const fullPath = path.join(dir, entry.name);

        if (entry.isDirectory()) {

            const result = findExecutable(fullPath);

            if (result) {
                return result;
            }

        } else if (entry.name === executableName) {

            return fullPath;

        }

    }

    return null;

}

const executable = findExecutable(
    path.join(__dirname, "bin")
);

if (!executable) {

    console.error(
        "BoreHook CLI is not installed correctly.\n" +
        "Please reinstall using:\n\n" +
        "    npm install -g @borehook/borecli"
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

child.on("exit", code => {
    process.exit(code ?? 0);
});

child.on("error", err => {

    console.error("Failed to start BoreHook CLI.");
    console.error(err.message);

    process.exit(1);

});