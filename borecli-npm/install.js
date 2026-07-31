const fs = require("fs");
const path = require("path");
const os = require("os");
const { https } = require("follow-redirects");
const AdmZip = require("adm-zip");
const tar = require("tar");

const OWNER = "CHI-NONSO1";
const REPO = "borecli";

const API =
    `https://api.github.com/repos/${OWNER}/${REPO}/releases/latest`;

const BIN_DIR = path.join(__dirname, "bin");

fs.mkdirSync(BIN_DIR, { recursive: true });

function request(url) {
    return new Promise((resolve, reject) => {

        https.get(url, {
            headers: {
                "User-Agent": "borecli-installer"
            }
        }, res => {

            let data = "";

            res.on("data", chunk => {
                data += chunk;
            });

            res.on("end", () => {

                if (res.statusCode >= 400) {
                    reject(
                        new Error(
                            `HTTP ${res.statusCode}`
                        )
                    );
                    return;
                }

                resolve(data);

            });

        }).on("error", reject);

    });
}

function download(url, destination) {

    return new Promise((resolve, reject) => {

        console.log(`Downloading\n${url}\n`);

        https.get(url, {
            headers: {
                "User-Agent": "borecli-installer"
            }
        }, response => {

            if (response.statusCode >= 400) {

                reject(
                    new Error(
                        `Download failed (${response.statusCode})`
                    )
                );

                return;
            }

            const total = Number(
                response.headers["content-length"] || 0
            );

            let downloaded = 0;

            const file = fs.createWriteStream(destination);

            response.on("data", chunk => {

                downloaded += chunk.length;

                if (total) {

                    process.stdout.write(
                        `\r${(
                            downloaded /
                            total *
                            100
                        ).toFixed(1)}%`
                    );

                }

            });

            response.pipe(file);

            file.on("finish", () => {

                file.close();

                console.log("\nDownload complete.");

                resolve();

            });

        }).on("error", reject);

    });

}

async function main() {

    console.log("Checking latest BoreHook release...");

    const release = JSON.parse(
        await request(API)
    );

    const tag = release.tag_name;

    let asset;

    switch (os.platform()) {

        case "win32":
            asset = `bore-${tag}-windows.zip`;
            break;

        case "linux":
            asset = `bore-${tag}-linux.tar.gz`;
            break;

        case "darwin":
            asset = `bore-${tag}-macos.tar.gz`;
            break;

        default:
            throw new Error(
                `Unsupported platform: ${os.platform()}`
            );

    }

    const url =
        `https://github.com/${OWNER}/${REPO}` +
        `/releases/download/${tag}/${asset}`;

    const archive =
        path.join(__dirname, asset);

    await download(
        url,
        archive,
    );

    console.log("Extracting...");

    if (os.platform() === "win32") {

        const zip = new AdmZip(archive);

        zip.extractAllTo(
            BIN_DIR,
            true,
        );

    } else {

        await tar.x({

            file: archive,
            cwd: BIN_DIR,

        });

        const executable =
            path.join(
                BIN_DIR,
                "bore",
            );

        fs.chmodSync(
            executable,
            0o755,
        );

    }

    fs.unlinkSync(
        archive,
    );

    console.log("");

    console.log(
        "✔ BoreHook CLI installed successfully."
    );

}

main().catch(err => {

    console.error("");

    console.error(
        "Installation failed."
    );

    console.error(
        err.message,
    );

    process.exit(1);

});