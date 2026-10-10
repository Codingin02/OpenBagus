"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

async function main() {
    const directory = path.resolve(process.argv[2]);
    const request = JSON.parse(fs.readFileSync(0, "utf8"));
    const settings = JSON.parse(fs.readFileSync(path.join(directory, "settings.json"), "utf8"));
    if (settings.consent !== true) return { status: "CLOUD_DISABLED" };
    const { init, getAuthToken } = require(path.join(directory, "node_modules/@heyputer/puter.js/src/init.cjs"));
    const secret = path.join(directory, "puter-auth.dpapi.txt");
    const powershell = path.join(process.env.SystemRoot, "System32/WindowsPowerShell/v1.0/powershell.exe");
    const run = (code, input = "") => spawnSync(powershell, ["-NoProfile", "-NonInteractive", "-Command", code], {
        input, encoding: "utf8", windowsHide: true, env: { ...process.env, OPENBAGUS_AUTH_FILE: secret }
    });
    if (request.action === "login") {
        const token = await getAuthToken();
        if (!token) return { status: "CLOUD_AUTH_FAILED" };
        const stored = run("$ErrorActionPreference='Stop'; $s=ConvertTo-SecureString ([Console]::In.ReadToEnd()) -AsPlainText -Force; ConvertFrom-SecureString $s | Set-Content -LiteralPath $env:OPENBAGUS_AUTH_FILE -Encoding ASCII", token);
        return { status: stored.status === 0 ? "CLOUD_AUTH_READY" : "CLOUD_AUTH_FAILED" };
    }
    if (request.action !== "chat") return { status: "CLOUD_FAILED" };
    const decrypted = run("$ErrorActionPreference='Stop'; $s=Get-Content -LiteralPath $env:OPENBAGUS_AUTH_FILE | ConvertTo-SecureString; $p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s); try { [Console]::Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($p)) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p) }");
    if (decrypted.status !== 0 || !decrypted.stdout.trim()) return { status: "CLOUD_AUTH_MISSING" };
    const puter = init(decrypted.stdout.trim());
    const response = await puter.ai.chat(request.prompt, { temperature: request.temperature, max_tokens: request.max_tokens, normalize: true });
    const content = response?.message?.content;
    const text = typeof content === "string" ? content : Array.isArray(content) ? content.map(c => c.text || "").join("") : "";
    return { status: text ? "CLOUD_OK" : "CLOUD_FAILED", text };
}

main().then(result => { process.stdout.write(JSON.stringify(result) + "\n"); process.exit(0); }).catch(error => {
    const code = String(error?.code || error?.error?.code || "").toLowerCase();
    process.stdout.write(JSON.stringify({ status: /quota|allowance|insufficient|rate.limit/.test(code) ? "CLOUD_QUOTA_EXHAUSTED" : "CLOUD_FAILED" }) + "\n");
    process.exit(1);
});
