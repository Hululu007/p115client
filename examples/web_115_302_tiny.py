#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 3)
__doc__ = """\
    🛫 115 302 微型版，仅支持用 pickcode 或 sha1 查询 🛬

此版本不依赖于 p115client 和 pycryptodome，且 Python 版本可低于 3.10

查询示例：

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
"""
__requirements__ = ["flask", "urllib3"]

if __name__ == "__main__":
    from argparse import ArgumentParser, RawTextHelpFormatter

    parser = ArgumentParser(description=__doc__, formatter_class=RawTextHelpFormatter)
    parser.add_argument("-cp", "--cookies-path", help="cookies 文件保存路径，默认为当前工作目录下的 115-cookies.txt")
    parser.add_argument("-H", "--host", default="0.0.0.0", help="ip 或 hostname，默认值：'0.0.0.0'")
    parser.add_argument("-P", "--port", default=8000, type=int, help="端口号，默认值：8000")
    parser.add_argument("-v", "--version", action="store_true", help="输出版本号")
    args = parser.parse_args()
    if args.version:
        print(".".join(map(str, __version__)))
        raise SystemExit(0)
else:
    cookies = open("115-cookies.txt", encoding="latin-1").read()

try:
    from flask import redirect, request, Flask, Response
    from urllib3 import PoolManager
except ImportError:
    from sys import executable
    from subprocess import run
    run([executable, "-m", "pip", "install", "-U", *__requirements__], check=True)
    from flask import redirect, request, Flask, Response
    from urllib3 import PoolManager

from base64 import b64decode, b64encode
from functools import partial
from string import hexdigits
try:
    from orjson import loads
except ImportError:
    from json import loads


G_kts = b"\xf0\xe5i\xae\xbf\xdc\xbf\x8a\x1aE\xe8\xbe}\xa6s\xb8\xde\x8f\xe7\xc4E\xda\x86\xc4\x9bd\x8b\x14j\xb4\xf1\xaa8\x015\x9e&i,\x86\x00kO\xa564b\xa6*\x96h\x18\xf2J\xfd\xbdk\x97\x8fM\x8f\x89\x13\xb7l\x8e\x93\xed\x0e\rH>\xd7/\x88\xd8\xfe\xfe~\x86P\x95O\xd1\xeb\x83&4\xdbf{\x9c~\x9dz\x812\xea\xb63\xde:\xa9Y4f;\xaa\xba\x81`H\xb9\xd5\x81\x9c\xf8l\x84w\xffTx&_\xbe\xe8\x1e6\x9f4\x80\\E,\x9bv\xd5\x1b\x8f\xcc\xc3\xb8\xf5"
RSA_e = 0x8686980c0f5a24c4b9d43020cd2c22703ff3f450756529058b1cf88f09b8602136477198a6e2683149659bd122c33592fdb5ad47944ad1ea4d36c6b172aad6338c3bb6ac6227502d010993ac967d1aef00f0c8e038de2e4d3bc2ec368af2e9f10a6f1eda4f7262f136420c07c331b871bf139f74f3010e3c4fe57df3afb71683 
RSA_n = 0x10001
SHA1_TO_PICKCODE = {} # type: dict[str, str]

to_bytes = partial(int.to_bytes, byteorder="big", signed=False)
from_bytes = partial(int.from_bytes, byteorder="big", signed=False)
urlopen = PoolManager(128).request

app = Flask(__name__)


def acc_step(start, stop, step=1):
    for i in range(start + step, stop, step):
        yield start, i, step
        start = i
    if start != stop:
        yield start, stop, stop - start


def bytes_xor(v1, v2):
    return to_bytes(from_bytes(v1) ^ from_bytes(v2), len(v1))


def gen_key(rand_key, sk_len) -> bytearray:
    xor_key = bytearray()
    append = xor_key.append
    if rand_key and sk_len > 0:
        length = sk_len * (sk_len - 1)
        index = 0
        for i in range(sk_len):
            x = (rand_key[i] + G_kts[index]) & 0xff
            append(G_kts[length] ^ x)
            length -= sk_len
            index += sk_len
    return xor_key


def pad_pkcs1_v1_5(message):
    return from_bytes(b"\x00" + b"\x02" * (126 - len(message)) + b"\x00" + message)


def xor(src, key):
    src = memoryview(src)
    key = memoryview(key)
    secret = bytearray()
    i = len(src) & 0b11
    if i:
        secret += bytes_xor(src[:i], key[:i])
    for i, j, s in acc_step(i, len(src), len(key)):
        secret += bytes_xor(src[i:j], key[:s])
    return secret


def encrypt(data):
    "RSA 加密"
    xor_text = bytearray(16)
    tmp = memoryview(xor(data, b"\x8d\xa5\xa5\x8d"))[::-1]
    xor_text += xor(tmp, b"x\x06\xadL3\x86]\x18L\x01?F")
    cipher_data = bytearray()
    view = memoryview(xor_text)
    for l, r, _ in acc_step(0, len(view), 117):
        cipher_data += to_bytes(pow(pad_pkcs1_v1_5(view[l:r]), RSA_n, RSA_e), 128)
    return b64encode(cipher_data)


def decrypt(cipher_data):
    "RSA 解密"
    cipher_data = memoryview(b64decode(cipher_data))
    data = bytearray()
    for l, r, _ in acc_step(0, len(cipher_data), 128):
        p = pow(from_bytes(cipher_data[l:r]), RSA_n, RSA_e)
        b = to_bytes(p, (p.bit_length() + 0b111) >> 3)
        data += memoryview(b)[b.index(0)+1:]
    m = memoryview(data)
    key_l = gen_key(m[:16], 12)
    tmp = memoryview(xor(m[16:], key_l))[::-1]
    return xor(tmp, b"\x8d\xa5\xa5\x8d")


def find_query_value(query, key):
    index = query.find(key+"=")
    if index >= 0:
        start = index + len(key) + 1
        stop = query.find("&", start)
        if stop == -1:
            return query[start:].strip()
        else:
            return query[start:stop].strip()
    return ""


def get_pickcode_for_sha1(sha1):
    pickcode = SHA1_TO_PICKCODE.get(sha1)
    if pickcode:
        return pickcode
    resp = urlopen(
        "GET", 
        f"https://webapi.115.com/files/shasearch?sha1={sha1}", 
        headers={"Cookie": cookies}, 
    ).json()
    if resp["state"]:
        info = resp["data"]
        pickcode = SHA1_TO_PICKCODE[sha1] = info["pick_code"]
        return pickcode


def get_downurl(pickcode, user_agent = ""):
    """获取文件的下载链接
    """
    pickcode_bytes = bytes(pickcode, "ascii")
    resp = urlopen(
        "POST", 
        "https://proapi.115.com/app/chrome/downurl", 
        fields={"data": encrypt(b'{"pickcode":"%s","pick_code":"%s"}' % (pickcode_bytes, pickcode_bytes)).decode("ascii")}, 
        headers={"Cookie": cookies, "User-Agent": user_agent}, 
    ).json()
    if resp["state"]:
        resp["data"] = loads(decrypt(resp["data"]))
    return resp


@app.route("/", methods=["GET", "HEAD"])
@app.route("/<path:name>", methods=["GET", "HEAD"])
def index(name=""):
    query_string = request.query_string.decode().strip()
    pickcode = find_query_value(query_string, "pickcode")
    if not pickcode:
        sha1 = find_query_value(query_string, "sha1")
        if sha1:
            if sha1.strip(hexdigits):
                return Response(f"bad sha1: {sha1!r}", 400)
        elif len(query_string) == 40 and not query_string.strip(hexdigits):
            sha1 = query_string
        if sha1:
            pickcode = get_pickcode_for_sha1(sha1.upper())
            if not pickcode:
                return Response(f"no file with sha1: {sha1!r}", 404)
    if not pickcode:
        pickcode = query_string
    if not pickcode.isalnum():
        return Response(f"bad pickcode: {pickcode!r}", 400)
    user_agent = request.headers.get("user-agent", "")
    resp = get_downurl(pickcode.lower(), user_agent)
    if resp["state"]:
        item = next(iter(resp["data"].values()))
        if item["url"]:
            return redirect(item["url"]["url"])
    return Response(f"no file with pickcode: {pickcode!r}", 404)


if __name__ == "__main__":
    cookies_path = args.cookies_path or "115-cookies.txt"
    cookies = open(cookies_path, encoding="latin-1").read()
    print(__doc__)
    app.run(
        host=args.host, 
        port=args.port, 
        threaded=True, 
        extra_files=cookies_path, 
    )

