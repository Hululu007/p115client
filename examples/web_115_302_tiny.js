#!/usr/bin/env node

const { readFileSync } = require("fs");
const { createServer } = require("http");
const { request } = require("https");
const { networkInterfaces } = require("os");
const { parse } = require("url");

const LICENSE = "GPLv3"
const VERSION = "0.0.2"
const AUTHOR = "ChenyangGao <https://chenyanggao.github.io>"
const DOC = `usage: web_115_302_tiny.js [-h] [-c COOKIES] [-cp COOKIES_PATH] [-H HOST] [-P PORT] [-v]

    🛫 115 302 微型版 (\x1b[4;5;34m${AUTHOR}\x1b[0m) 🛬

💡 目前仅支持用 pickcode 或 sha1 查询

🌰 查询示例：

    1. 查询 pickcode
        http://localhost:8000?ecjq9ichcb40lzlvx
        http://localhost:8000?pickcode=ecjq9ichcb40lzlvx
    2. 带（任意）名字查询 pickcode
        http://localhost:8000/Novembre.2022.FRENCH.2160p.BluRay.DV.HEVC.DTS-HD.MA.5.1.mkv?ecjq9ichcb40lzlvx
        http://localhost:8000/Novembre.2022.FRENCH.2160p.BluRay.DV.HEVC.DTS-HD.MA.5.1.mkv?pickcode=ecjq9ichcb40lzlvx
    3. 查询 sha1
        http://localhost:8000?E7FAA0BE343AF2DA8915F2B694295C8E4C91E691
        http://localhost:8000?sha1=E7FAA0BE343AF2DA8915F2B694295C8E4C91E691
    4. 带（任意）名字查询 sha1
        http://localhost:8000/Novembre.2022.FRENCH.2160p.BluRay.DV.HEVC.DTS-HD.MA.5.1.mkv?E7FAA0BE343AF2DA8915F2B694295C8E4C91E691
        http://localhost:8000/Novembre.2022.FRENCH.2160p.BluRay.DV.HEVC.DTS-HD.MA.5.1.mkv?sha1=E7FAA0BE343AF2DA8915F2B694295C8E4C91E691

options:
  -h, --help            show this help message and exit
  -c COOKIES, --cookies COOKIES
                        cookies 字符串
  -cp COOKIES_PATH, --cookies-path COOKIES_PATH
                        cookies 文件保存路径，默认为当前工作目录下的 115-cookies.txt
  -H HOST, --host HOST  ip 或 hostname，默认值：'0.0.0.0'
  -P PORT, --port PORT  端口号，默认值：8000
  -v, --version         输出版本号`

const G_kts = new Uint8Array([
    0xf0, 0xe5, 0x69, 0xae, 0xbf, 0xdc, 0xbf, 0x8a, 
    0x1a, 0x45, 0xe8, 0xbe, 0x7d, 0xa6, 0x73, 0xb8, 
    0xde, 0x8f, 0xe7, 0xc4, 0x45, 0xda, 0x86, 0xc4, 
    0x9b, 0x64, 0x8b, 0x14, 0x6a, 0xb4, 0xf1, 0xaa, 
    0x38, 0x01, 0x35, 0x9e, 0x26, 0x69, 0x2c, 0x86, 
    0x00, 0x6b, 0x4f, 0xa5, 0x36, 0x34, 0x62, 0xa6, 
    0x2a, 0x96, 0x68, 0x18, 0xf2, 0x4a, 0xfd, 0xbd, 
    0x6b, 0x97, 0x8f, 0x4d, 0x8f, 0x89, 0x13, 0xb7, 
    0x6c, 0x8e, 0x93, 0xed, 0x0e, 0x0d, 0x48, 0x3e, 
    0xd7, 0x2f, 0x88, 0xd8, 0xfe, 0xfe, 0x7e, 0x86, 
    0x50, 0x95, 0x4f, 0xd1, 0xeb, 0x83, 0x26, 0x34, 
    0xdb, 0x66, 0x7b, 0x9c, 0x7e, 0x9d, 0x7a, 0x81, 
    0x32, 0xea, 0xb6, 0x33, 0xde, 0x3a, 0xa9, 0x59, 
    0x34, 0x66, 0x3b, 0xaa, 0xba, 0x81, 0x60, 0x48, 
    0xb9, 0xd5, 0x81, 0x9c, 0xf8, 0x6c, 0x84, 0x77, 
    0xff, 0x54, 0x78, 0x26, 0x5f, 0xbe, 0xe8, 0x1e, 
    0x36, 0x9f, 0x34, 0x80, 0x5c, 0x45, 0x2c, 0x9b, 
    0x76, 0xd5, 0x1b, 0x8f, 0xcc, 0xc3, 0xb8, 0xf5, 
]);
const RSA_e = 0x8686980c0f5a24c4b9d43020cd2c22703ff3f450756529058b1cf88f09b8602136477198a6e2683149659bd122c33592fdb5ad47944ad1ea4d36c6b172aad6338c3bb6ac6227502d010993ac967d1aef00f0c8e038de2e4d3bc2ec368af2e9f10a6f1eda4f7262f136420c07c331b871bf139f74f3010e3c4fe57df3afb71683n;
const RSA_n = 0x10001n;
const SHA1_TO_PICKCODE = new Map();

function toBytes(value, length) {
    if (length == undefined)
        length = Math.ceil(value.toString(16).length / 2);
    const buffer = new Uint8Array(length);
    for (let i = length - 1; i >= 0; i--) {
        buffer[i] = Number(value & 0xffn);
        value >>= 8n;
    }
    return buffer;
}

function fromBytes(bytes) {
    let intVal = 0n;
    for (const b of bytes)
        intVal = (intVal << 8n) | BigInt(b);
    return intVal;
}

function* accStep(start, stop, step = 1) {
    for (let i = start + step; i < stop; i += step) {
        yield [start, i, step];
        start = i;
    }
    if (start !== stop)
        yield [start, stop, stop - start];
}

function bytesXor(v1, v2) {
    const result = new Uint8Array(v1.length);
    for (let i = 0; i < v1.length; i++)
        result[i] = v1[i] ^ v2[i];
    return result;
}

function genKey(randKey, skLen) {
    const xorKey = new Uint8Array(skLen);
    let length = skLen * (skLen - 1);
    let index = 0;
    for (let i = 0; i < skLen; i++) {
        const x = (randKey[i] + G_kts[index]) & 0xff;
        xorKey[i] = G_kts[length] ^ x;
        length -= skLen;
        index += skLen;
    }
    return xorKey;
}

function padPkcs1V1_5(message) {
    const msg_len = message.length
    const buffer = new Uint8Array(128);
    buffer.fill(0x02, 1, 127 - msg_len);
    buffer.set(message, 128 - msg_len);
    return fromBytes(buffer);
}

function xor(src, key) {
    const buffer = new Uint8Array(src.length);
    const i = src.length & 0b11;
    if (i)
        buffer.set(bytesXor(src.subarray(0, i), key.subarray(0, i)));
    for (const [j, k] of accStep(i, src.length, key.length))
        buffer.set(bytesXor(src.subarray(j, k), key), j);
    return buffer;
}

function pow(base, exponent, modulus) {
    if (modulus === 1n)
        return 0n;
    let result = 1n;
    base %= modulus;
    while (exponent) {
        if (exponent & 1n)
            result = (result * base) % modulus;
        exponent = exponent >> 1n;
        base = (base * base) % modulus;
    }
    return result;
}

function encrypt(data) {
    if (typeof data === "string" || data instanceof String)
        data = (new TextEncoder()).encode(data);
    const xorText = new Uint8Array(16 + data.length);
    xorText.set(xor(
        xor(data, new Uint8Array([0x8d, 0xa5, 0xa5, 0x8d])).reverse(), 
        new Uint8Array([0x78, 0x06, 0xad, 0x4c, 0x33, 0x86, 0x5d, 0x18, 0x4c, 0x01, 0x3f, 0x46])
    ), 16);
    const cipherData = new Uint8Array(Math.ceil(xorText.length / 117) * 128);
    let start = 0;
    for (const [l, r] of accStep(0, xorText.length, 117))
        cipherData.set(toBytes(pow(padPkcs1V1_5(xorText.subarray(l, r)), RSA_n, RSA_e), 128), start, start += 128);
    return Buffer.from(cipherData).toString("base64");
}

function decrypt(cipherData) {
    const cipher_data = new Uint8Array(Buffer.from(cipherData, "base64"));
    let data = [];
    for (const [l, r] of accStep(0, cipher_data.length, 128)) {
        const p = pow(fromBytes(cipher_data.subarray(l, r)), RSA_n, RSA_e);
        const b = toBytes(p);
        data.push(...b.subarray(b.indexOf(0) + 1));
    }
    data = new Uint8Array(data);
    const keyL = genKey(data.subarray(0, 16), 12);
    const tmp = xor(data.subarray(16), keyL).reverse();
    return (new TextDecoder("utf-8")).decode(xor(tmp, new Uint8Array([0x8d, 0xa5, 0xa5, 0x8d])));
}

function getPickcodeForSha1(sha1, headers) {
    return new Promise((resolve, reject) => {
        let pickcode = SHA1_TO_PICKCODE.get(sha1);
        if (pickcode)
            return resolve(pickcode)
        const options = {
            hostname: "webapi.115.com", 
            path: `/files/shasearch?sha1=${sha1}`, 
            method: "GET", 
            headers: headers, 
        };
        const req = request(options, (res) => {
            let data = "";
            res.on("data", (chunk) => {
                data += chunk;
            });
            res.on("end", () => {
                try {
                    const response = JSON.parse(data);
                    if (response.state) {
                        pickcode = response["data"]["pick_code"];
                        SHA1_TO_PICKCODE.set(sha1, pickcode);
                        resolve(pickcode);
                    } else
                        reject(data);
                } catch (e) {
                    reject(data);
                }
            });
        });
        req.on("error", (e) => {
            reject(e);
        });
        req.end();
      });
}

function getUrl(pickcode, headers) {
    return new Promise((resolve, reject) => {
        const data = `data=${encodeURIComponent(encrypt(`{"pick_code":"${pickcode}"}`))}`;
        headers["Content-Type"] = "application/x-www-form-urlencoded";
        headers["Content-Length"] = Buffer.byteLength(data);
        const options = {
            hostname: "proapi.115.com", 
            path: "/android/2.0/ufile/download", 
            method: "POST", 
            headers: headers, 
        };
        const req = request(options, (res) => {
            let data = "";
            res.on("data", (chunk) => {
                data += chunk;
            });
            res.on("end", () => {
                try {
                    const response = JSON.parse(data);
                    if (response.state)
                        resolve(JSON.parse(decrypt(response.data)).url);
                    else
                        reject(data);
                } catch (e) {
                    reject(data);
                }
            });
        });
        req.on("error", (e) => {
            reject(e);
        });
        req.write(data);
        req.end();
      });
}

function getLocalIP() {
    let localIP;
    for (const iface of Object.values(networkInterfaces()))
        for (const address of iface)
            if (address.family === "IPv4" && !address.internal)
                if (localIP = address.address)
                    return localIP;
}

const args = {
    host: "0.0.0.0", 
    port: 8000, 
    cookies: null, 
};

const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
    switch(argv[i]) {
        case "-H":
        case "--host":
            args.host = argv[++i];
            break;
        case "-P":
        case "--port":
            args.port = Number.parseInt(argv[++i]);
            break;
        case "-c":
        case "--cookies":
            args.cookies = argv[++i].trim();
            break;
        case "-cp":
        case "--cookies-path":
            args.cookies = readFileSync(argv[++i], "latin1").trim();
            break;
        case "-v":
        case "--version":
            console.log(VERSION);
            process.exit(0);
        case "-h":
        case "--help":
            console.log(DOC);
            process.exit(0);
    }
}

if (!args.cookies)
    args.cookies = readFileSync("115-cookies.txt", "latin1").trim();

const server = createServer(async (req, res) => {
    const [start_s, start_ns] = process.hrtime();
    let status_code = 200;
    try {
        const parsedUrl = parse(req.url, true);
        if (!parsedUrl.search) {
            status_code = 400;
            res.writeHead(status_code, {"content-type": "text/plain; charset=utf-8"});
            res.end("no pickcode provided");
            return;
        }
        const query = decodeURIComponent(parsedUrl.search.slice(1)).trim();
        const queryParams = parsedUrl.query;
        let pickcode = (queryParams.pickcode || "").trim();
        if (!pickcode) {
            let sha1 = (queryParams.sha1 || "").trim();
            if (sha1) {
                if (!/^[0-9a-fA-F]+$/.test(sha1)) {
                    status_code = 400;
                    res.writeHead(status_code, {"content-type": "text/plain; charset=utf-8"});
                    res.end(`bad sha1: ${sha1}`);
                    return;
                }
            } else if (query.length == 40 && /^[0-9a-fA-F]+$/.test(query))
                sha1 = query;
            if (sha1) {
                pickcode = await getPickcodeForSha1(sha1.toUpperCase(), {
                    "Cookie": args.cookies
                });
            }
        }
        if (!pickcode)
            pickcode = query;
        if (!/^[0-9a-zA-Z]+$/.test(pickcode)) {
            status_code = 400;
            res.writeHead(status_code, {"content-type": "text/plain; charset=utf-8"});
            res.end(`bad pickcode: ${pickcode}`);
            return;
        }
        const user_agent = req.headers["user-agent"];
        const url = await getUrl(pickcode, {
            "Cookie": args.cookies, 
            "User-Agent": user_agent
        });
        status_code = 302;
        res.writeHead(status_code, { "location": url });
        res.end();
    } catch (e) {
        status_code = 500;
        res.writeHead(status_code);
        res.end(e.message);
    } finally {
        const [stop_s, stop_ns] = process.hrtime();
        let statusColor;
        if (status_code < 300)
            statusColor = 32;
        else if (status_code < 400)
            statusColor = 33;
        else 
            statusColor = 31;
        const duration = (stop_s * 1000 + stop_ns / 1e6) - (start_s * 1000 + start_ns / 1e6);
        console.log(`[\x1b[1m${(new Date()).toISOString()}\x1b[0m] \x1b[5;37m${req.socket.remoteAddress}\x1b[0m - \x1b[36m${req.method}\x1b[0m \x1b[4;34m${req.url}\x1b[0m - \x1b[${statusColor}m${status_code}\x1b[0m - ${duration.toFixed(3)} ms`);
    }
});
server.listen(args.port, args.host, () => {
    console.log(DOC);
    console.log("\n * Serving \x1b[1mnodejs\x1b[0m app '\x1b[4;34mweb_115_302_tiny\x1b[0m'")
    if (args.host == "0.0.0.0")
        console.log(" * Running on all addresses (\x1b[4;34m0.0.0.0\x1b[0m)")
    console.log(` * Running on \x1b[4;34mhttp://127.0.0.1:${args.port}\x1b[0m`)
    if (args.host == "0.0.0.0")
        console.log(` * Running on \x1b[4;34mhttp://${getLocalIP()}:${args.port}\x1b[0m`);
    else
        console.log(` * Running on \x1b[4;34mhttp://${args.host}:${args.port}\x1b[0m`);
    console.log("\x1b[33mPress CTRL+C to quit\x1b[0m")
});
