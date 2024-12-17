#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 6)
__all__ = ["make_application"]
__licence__ = "GPLv3 <https://www.gnu.org/licenses/gpl-3.0.txt>"
__doc__ = """\
                            \x1b[1;5m🛫 115 302 微型版 🛬\x1b[0m

    ╭────────────────────── \x1b[31mWelcome to \x1b[1mweb_115_302_tiny.py\x1b[0m ────────────────────────╮
    │                                                                              │
    │  \x1b[35mmaintained by\x1b[0m \x1b[3;5;31m❤\x1b[0m     \x1b[32mChenyangGao \x1b[4;34mhttps://chenyanggao.github.io\x1b[0m               │
    │                                                                              │
    │                      \x1b[32mGithub      \x1b[4;34mhttps://github.com/ChenyangGao/p115client/\x1b[0m  │
    │                                                                              │
    │                      \x1b[32mlicence     \x1b[4;34mhttps://www.gnu.org/licenses/gpl-3.0.txt\x1b[0m    │
    │                                                                              │
    │                      \x1b[32mversion     \x1b[1;36m0.0.6\x1b[0m                                       │
    │                                                                              │
    ╰──────────────────────────────────────────────────────────────────────────────╯

> 网盘文件支持用 \x1b[3;36mpickcode\x1b[0m、\x1b[3;36mid\x1b[0m、\x1b[3;36msha1\x1b[0m 或 \x1b[3;36mname\x1b[0m 查询
> 分享文件支持用 \x1b[3;36mid\x1b[0m 或 \x1b[3;36mname\x1b[0m 查询

⏰ 此版本不依赖于 \x1b[31mp115client\x1b[0m 和 \x1b[31mpycryptodome\x1b[0m，至少要求 \x1b[31mpython \x1b[1m3.8\x1b[0m

🌰 查询示例：

    0. 查询 \x1b[3;36mpickcode\x1b[0m
        \x1b[4;34mhttp://localhost:8000?ecjq9ichcb40lzlvx\x1b[0m
        \x1b[4;34mhttp://localhost:8000/ecjq9ichcb40lzlvx\x1b[0m
        http://localhost:8000?pickcode=ecjq9ichcb40lzlvx\x1b[0m
    1. 带（任意）名字查询 \x1b[3;36mpickcode\x1b[0m
        \x1b[4;34mhttp://localhost:8000/Novembre.2022.FRENCH.2160p.BluRay.DV.HEVC.DTS-HD.MA.5.1.mkv?ecjq9ichcb40lzlvx\x1b[0m
        \x1b[4;34mhttp://localhost:8000/Novembre.2022.FRENCH.2160p.BluRay.DV.HEVC.DTS-HD.MA.5.1.mkv?pickcode=ecjq9ichcb40lzlvx\x1b[0m
    2. 查询 \x1b[3;36mid\x1b[0m
        \x1b[4;34mhttp://localhost:8000?2691590992858971545\x1b[0m
        \x1b[4;34mhttp://localhost:8000/2691590992858971545\x1b[0m
        \x1b[4;34mhttp://localhost:8000?id=2691590992858971545\x1b[0m
    3. 带（任意）名字查询 \x1b[3;36mid\x1b[0m
        \x1b[4;34mhttp://localhost:8000/Novembre.2022.FRENCH.2160p.BluRay.DV.HEVC.DTS-HD.MA.5.1.mkv?2691590992858971545\x1b[0m
        \x1b[4;34mhttp://localhost:8000/Novembre.2022.FRENCH.2160p.BluRay.DV.HEVC.DTS-HD.MA.5.1.mkv?id=2691590992858971545\x1b[0m
    4. 查询 \x1b[3;36msha1\x1b[0m
        \x1b[4;34mhttp://localhost:8000?E7FAA0BE343AF2DA8915F2B694295C8E4C91E691\x1b[0m
        \x1b[4;34mhttp://localhost:8000/E7FAA0BE343AF2DA8915F2B694295C8E4C91E691\x1b[0m
        \x1b[4;34mhttp://localhost:8000?sha1=E7FAA0BE343AF2DA8915F2B694295C8E4C91E691\x1b[0m
    5. 带（任意）名字查询 \x1b[3;36msha1\x1b[0m
        \x1b[4;34mhttp://localhost:8000/Novembre.2022.FRENCH.2160p.BluRay.DV.HEVC.DTS-HD.MA.5.1.mkv?E7FAA0BE343AF2DA8915F2B694295C8E4C91E691\x1b[0m
        \x1b[4;34mhttp://localhost:8000/Novembre.2022.FRENCH.2160p.BluRay.DV.HEVC.DTS-HD.MA.5.1.mkv?sha1=E7FAA0BE343AF2DA8915F2B694295C8E4C91E691\x1b[0m
    6. 查询 \x1b[3;36mname\x1b[0m（直接以路径作为 \x1b[3;36mname\x1b[0m，且不要有任何查询参数）
        \x1b[4;34mhttp://localhost:8000/Novembre.2022.FRENCH.2160p.BluRay.DV.HEVC.DTS-HD.MA.5.1.mkv\x1b[0m
    7. 查询分享文件（如果是你自己的分享，则无须提供密码 \x1b[3;36mreceive_code\x1b[0m）
        \x1b[4;34mhttp://localhost:8000?share_code=sw68md23w8m&receive_code=q353&id=2580033742990999218\x1b[0m
        \x1b[4;34mhttp://localhost:8000?share_code=sw68md23w8m&receive_code=q353&id=2580033742990999218\x1b[0m
        \x1b[4;34mhttp://localhost:8000?share_code=sw68md23w8m&id=2580033742990999218\x1b[0m
    8. 带（任意）名字查询分享文件（如果是你自己的分享，则无须提供密码 \x1b[3;36mreceive_code\x1b[0m）
        \x1b[4;34mhttp://localhost:8000/Cosmos.S01E01.1080p.AMZN.WEB-DL.DD+5.1.H.264-iKA.mkv?share_code=sw68md23w8m&receive_code=q353&id=2580033742990999218\x1b[0m
        \x1b[4;34mhttp://localhost:8000/Cosmos.S01E01.1080p.AMZN.WEB-DL.DD+5.1.H.264-iKA.mkv?share_code=sw68md23w8m&id=2580033742990999218\x1b[0m
    9. 用 \x1b[3;36mname\x1b[0m 查询分享文件（直接以路径作为 \x1b[3;36mname\x1b[0m，且不要有 \x1b[3;36mid\x1b[0m 查询参数。如果是你自己的分享，则无须提供密码 \x1b[3;36mreceive_code\x1b[0m）
        \x1b[4;34mhttp://localhost:8000/Cosmos.S01E01.1080p.AMZN.WEB-DL.DD+5.1.H.264-iKA.mkv?share_code=sw68md23w8m&receive_code=q353\x1b[0m
        \x1b[4;34mhttp://localhost:8000/Cosmos.S01E01.1080p.AMZN.WEB-DL.DD+5.1.H.264-iKA.mkv?share_code=sw68md23w8m\x1b[0m
"""

if __name__ == "__main__":
    from argparse import ArgumentParser, RawTextHelpFormatter

    parser = ArgumentParser(description=__doc__, formatter_class=RawTextHelpFormatter)
    parser.add_argument("-c", "--cookies", default="", help="cookies 字符串，优先级高于 -cp/--cookies-path")
    parser.add_argument("-cp", "--cookies-path", default="", help="cookies 文件保存路径，默认为当前工作目录下的 115-cookies.txt")
    parser.add_argument("-H", "--host", default="0.0.0.0", help="ip 或 hostname，默认值：'0.0.0.0'")
    parser.add_argument("-P", "--port", default=8000, type=int, help="端口号，默认值：8000")
    parser.add_argument("-d", "--debug", action="store_true", help="启用调试，会输出更详细信息")
    parser.add_argument("-l", "--license", action="store_true", help="输出授权信息")
    parser.add_argument("-v", "--version", action="store_true", help="输出版本号")
    args = parser.parse_args()
    if args.version:
        print(".".join(map(str, __version__)))
        raise SystemExit(0)
    if args.license:
        print(__licence__)
        raise SystemExit(0)
    cookies = args.cookies.strip()
    if not cookies:
        cookies_path = args.cookies_path.strip() or "115-cookies.txt"
        cookies = open(cookies_path, encoding="latin-1").read().strip()

try:
    from blacksheep import redirect, text, Application, Request, Router
    from blacksheep.client import ClientSession
    from blacksheep.contents import FormContent
    from blacksheep.server.compression import use_gzip_compression
    from blacksheep.server.remotes.forwarding import ForwardedHeadersMiddleware
except ImportError:
    from sys import executable
    from subprocess import run
    run([executable, "-m", "pip", "install", "-U", "blacksheep"], check=True)
    from blacksheep import redirect, text, Application, Request, Router
    from blacksheep.client import ClientSession
    from blacksheep.contents import FormContent
    from blacksheep.server.compression import use_gzip_compression
    from blacksheep.server.remotes.forwarding import ForwardedHeadersMiddleware

from collections.abc import ItemsView, Mapping
from base64 import b64decode, b64encode
from functools import partial
from itertools import cycle
from string import digits, hexdigits
from urllib.parse import urlencode
try:
    from orjson import loads
except ImportError:
    from json import loads


G_kts = b"\xf0\xe5i\xae\xbf\xdc\xbf\x8a\x1aE\xe8\xbe}\xa6s\xb8\xde\x8f\xe7\xc4E\xda\x86\xc4\x9bd\x8b\x14j\xb4\xf1\xaa8\x015\x9e&i,\x86\x00kO\xa564b\xa6*\x96h\x18\xf2J\xfd\xbdk\x97\x8fM\x8f\x89\x13\xb7l\x8e\x93\xed\x0e\rH>\xd7/\x88\xd8\xfe\xfe~\x86P\x95O\xd1\xeb\x83&4\xdbf{\x9c~\x9dz\x812\xea\xb63\xde:\xa9Y4f;\xaa\xba\x81`H\xb9\xd5\x81\x9c\xf8l\x84w\xffTx&_\xbe\xe8\x1e6\x9f4\x80\\E,\x9bv\xd5\x1b\x8f\xcc\xc3\xb8\xf5"
RSA_e = 0x8686980c0f5a24c4b9d43020cd2c22703ff3f450756529058b1cf88f09b8602136477198a6e2683149659bd122c33592fdb5ad47944ad1ea4d36c6b172aad6338c3bb6ac6227502d010993ac967d1aef00f0c8e038de2e4d3bc2ec368af2e9f10a6f1eda4f7262f136420c07c331b871bf139f74f3010e3c4fe57df3afb71683 
RSA_n = 0x10001

to_bytes = partial(int.to_bytes, byteorder="big", signed=False)
from_bytes = partial(int.from_bytes, byteorder="big", signed=False)
get_webapi_url = cycle(("http://anxia.com/webapi", "http://v.anxia.com/webapi", "http://web.api.115.com")).__next__
get_proapi_url = cycle(("http://pro.api.115.com", "http://pro.api.115.com", "http://pro.api.115.com", "http://pro.api.115.com", "https://proapi.115.com")).__next__


def acc_step(start, stop, step=1):
    for i in range(start + step, stop, step):
        yield start, i, step
        start = i
    if start != stop:
        yield start, stop, stop - start


def bytes_xor(v1, v2):
    return to_bytes(from_bytes(v1) ^ from_bytes(v2), len(v1))


def gen_key(rand_key, sk_len) -> bytearray:
    xor_key = bytearray(sk_len)
    length = sk_len * (sk_len - 1)
    index = 0
    for i in range(sk_len):
        x = (rand_key[i] + G_kts[index]) & 0xff
        xor_key[i] = G_kts[length] ^ x
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
    xor_text = bytearray(16)
    tmp = memoryview(xor(data, b"\x8d\xa5\xa5\x8d"))[::-1]
    xor_text += xor(tmp, b"x\x06\xadL3\x86]\x18L\x01?F")
    cipher_data = bytearray()
    view = memoryview(xor_text)
    for l, r, _ in acc_step(0, len(view), 117):
        cipher_data += to_bytes(pow(pad_pkcs1_v1_5(view[l:r]), RSA_n, RSA_e), 128)
    return b64encode(cipher_data)


def decrypt(cipher_data):
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


def get_first(m: Mapping, *keys, default=None):
    for k in keys:
        if k in m:
            return m[k]
    return default


class LRUDict(dict):

    def __init__(self, maxsize: int = 0):
        self.maxsize = maxsize

    def __setitem__(self, key, value):
        self.pop(key, None)
        super().__setitem__(key, value)
        self.clean()

    def clean(self):
        if (maxsize := self.maxsize) > 0:
            pop = self.pop
            while len(self) > maxsize:
                try:
                    pop(next(iter(self)), None)
                except RuntimeError:
                    pass

    def setdefault(self, key, default=None):
        value = super().setdefault(key, default)
        self.clean()
        return value

    def update(self, *args, **pairs):
        pop = self.pop
        setitem = self.__setitem__
        for arg in args:
            if isinstance(arg, Mapping):
                try:
                    arg = arg.items()
                except (AttributeError, TypeError):
                    arg = ItemsView(arg)
            for key, val in arg:
                pop(key, None)
                setitem(key, val)
        if pairs:
            for key, val in pairs.items():
                pop(key, None)
                setitem(key, val)
        self.clean()


def make_application(cookies: str, debug: bool = False) -> Application:
    ID_TO_PICKCODE   = LRUDict(65536) # type: dict[int, str]
    SHA1_TO_PICKCODE = LRUDict(65536) # type: dict[str, str]
    NAME_TO_PICKCODE = LRUDict(65536) # type: dict[str, str]
    SHARE_NAME_TO_ID = LRUDict(65536) # type: dict[tuple[str, str], int]
    RECEIVE_CODE_MAP = {}             # type: dict[str, str]

    app = Application(router=Router(), show_error_details=debug)
    use_gzip_compression(app)
    client: ClientSession

    if debug:
        getattr(app, "logger").level = 10
    else:
        @app.exception_handler(Exception)
        async def redirect_exception_response(
            self, 
            request: Request, 
            exc: Exception, 
        ):
            if isinstance(exc, ValueError):
                return text(str(exc), 400)
            elif isinstance(exc, FileNotFoundError):
                return text(str(exc), 404)
            elif isinstance(exc, OSError):
                return text(str(exc), 503)
            else:
                return text(str(exc), 500)

    @app.on_middlewares_configuration
    def configure_forwarded_headers(app: Application):
        app.middlewares.insert(0, ForwardedHeadersMiddleware(accept_only_proxied_requests=False))

    @app.lifespan
    async def register_http_client():
        nonlocal client
        async with ClientSession(default_headers={"Cookie": cookies}) as client:
            app.services.register(ClientSession, instance=client)
            yield

    async def get_pickcode_to_id(id: int) -> str:
        pickcode = ID_TO_PICKCODE.get(id, "")
        if pickcode:
            return pickcode
        resp = await client.get(f"{get_webapi_url()}/files/file?file_id={id}")
        text = await resp.text()
        json = loads(text)
        if not json["state"]:
            raise FileNotFoundError(text)
        info = json["data"][0]
        pickcode = ID_TO_PICKCODE[id] = info["pick_code"]
        return pickcode

    async def get_pickcode_for_sha1(sha1: str) -> str:
        pickcode = SHA1_TO_PICKCODE.get(sha1, "")
        if pickcode:
            return pickcode
        resp = await client.get(f"{get_webapi_url()}/files/shasearch?sha1={sha1}")
        text = await resp.text()
        json = loads(text)
        if not json["state"]:
            raise FileNotFoundError(text)
        info = json["data"]
        pickcode = SHA1_TO_PICKCODE[sha1] = info["pick_code"]
        return pickcode

    async def get_pickcode_for_name(name: str) -> str:
        pickcode = NAME_TO_PICKCODE.get(name, "")
        if pickcode:
            return pickcode
        api = f"{get_webapi_url()}/files/search"
        payload = {"search_value": name, "limit": 1, "type": 99}
        suffix = name.rpartition(".")[-1]
        if suffix.isalnum():
            payload["suffix"] = suffix
        resp = await client.get(f"{api}?{urlencode(payload)}")
        text = await resp.text()
        json = loads(text)
        if get_first(json, "errno", "errNo") == 20021:
            payload.pop("suffix")
            resp = await client.get(f"{api}?{urlencode(payload)}")
            text = await resp.text()
            json = loads(text)
        if not json["state"] or not json["count"]:
            raise FileNotFoundError(text)
        info = json["data"][0]
        if info["n"] != name:
            raise FileNotFoundError(name)
        pickcode = NAME_TO_PICKCODE[name] = info["pc"]
        return pickcode

    async def share_get_id_for_name(share_code: str, receive_code: str, name: str) -> int:
        id = SHARE_NAME_TO_ID.get((share_code, name), 0)
        if id:
            return id
        api = f"{get_webapi_url()}/share/search"
        payload = {"share_code": share_code, "receive_code": receive_code, "search_value": name, "limit": 1, "type": 99}
        suffix = name.rpartition(".")[-1]
        if suffix.isalnum():
            payload["suffix"] = suffix
        resp = await client.get(f"{api}?{urlencode(payload)}")
        text = await resp.text()
        json = loads(text)
        if get_first(json, "errno", "errNo") == 20021:
            payload.pop("suffix")
            resp = await client.get(f"{api}?{urlencode(payload)}")
            text = await resp.text()
            json = loads(text)
        if not json["state"] or not json["data"]["count"]:
            raise FileNotFoundError(text)
        info = json["data"]["list"][0]
        if info["n"] != name:
            raise FileNotFoundError(name)
        id = SHARE_NAME_TO_ID[(share_code, name)] = int(info["fid"])
        return id

    async def get_downurl(pickcode: str, user_agent: bytes | str = b"") -> str:
        resp = await client.post(
            f"{get_proapi_url()}/android/2.0/ufile/download", 
            content=FormContent([("data", encrypt(b'{"pick_code":"%s"}' % bytes(pickcode, "ascii")).decode("utf-8"))]), 
            headers={b"User-Agent": user_agent}, 
        )
        text = await resp.text()
        json = loads(text)
        if not json["state"]:
            raise OSError(text)
        url = loads(decrypt(json["data"]))["url"]
        if not url:
            raise FileNotFoundError(text)
        return url

    async def get_share_downurl(share_code: str, receive_code: str, file_id: int):
        resp = await client.post(
            f"{get_proapi_url()}/app/share/downurl", 
            content=FormContent([("data", encrypt(f'{{"share_code":"{share_code}","receive_code":"{receive_code}","file_id":{file_id}}}'.encode("utf-8")).decode("utf-8"))]), 
        )
        text = await resp.text()
        json = loads(text)
        if not json["state"]:
            if json.get("errno") == 4100008 and RECEIVE_CODE_MAP.pop(share_code, None):
                receive_code = await get_receive_code(share_code)
                return await get_share_downurl(share_code, receive_code, file_id)
            raise OSError(text)
        url = loads(decrypt(json["data"]))["url"]
        if not url:
            raise FileNotFoundError(text)
        return url["url"]

    async def get_receive_code(share_code: str) -> str:
        receive_code = RECEIVE_CODE_MAP.get(share_code, "")
        if receive_code:
            return receive_code
        resp = await client.get(f"{get_webapi_url()}/share/shareinfo?share_code={share_code}")
        text = await resp.text()
        json = loads(text)
        if not json["state"]:
            raise FileNotFoundError(text)
        receive_code = RECEIVE_CODE_MAP[share_code] = json["data"]["receive_code"]
        return receive_code

    @app.router.route("/", methods=["GET", "HEAD", "POST"])
    @app.router.route("/<path:name>", methods=["GET", "HEAD", "POST"])
    async def index(
        request: Request, 
        name: str = "", 
        share_code: str = "", 
        receive_code: str = "", 
        pickcode: str = "", 
        id: int = 0, 
        sha1: str = "", 
    ):
        if share_code:
            if not receive_code:
                receive_code = await get_receive_code(share_code)
            elif len(receive_code) != 4:
                raise ValueError(f"bad receive_code: {receive_code!r}")
            if not id:
                if name:
                    id = await share_get_id_for_name(share_code, receive_code, name)
            if not id:
                raise FileNotFoundError(f"please specify id or name: share_code={share_code!r}")
            url = await get_share_downurl(share_code, receive_code, id)
        else:
            if pickcode:
                if len(pickcode) != 17:
                    raise ValueError(f"bad pickcode: {pickcode!r}")
            elif sha1:
                if len(sha1) != 40 or sha1.strip(hexdigits):
                    raise ValueError(f"bad sha1: {sha1!r}")
                pickcode = await get_pickcode_for_sha1(sha1.upper())
            elif id:
                pickcode = await get_pickcode_to_id(id)
            else:
                query = request.url.query
                if query:
                    query_string = query.decode("latin-1")
                    if len(query_string) == 17 and query_string.isalnum():
                        pickcode = query_string
                    elif len(query_string) == 40 and not query_string.strip(hexdigits):
                        pickcode = await get_pickcode_for_sha1(query_string.upper())
                    elif not query_string.strip(digits):
                        pickcode = await get_pickcode_to_id(int(query_string))
                    else:
                        raise ValueError(f"bad query string: {query_string!r}")
                elif name:
                    if len(name) == 17 and name.isalnum():
                        pickcode = name
                    elif len(name) == 40 and not name.strip(hexdigits):
                        pickcode = await get_pickcode_for_sha1(name.upper())
                    elif not name.strip(digits):
                        pickcode = await get_pickcode_to_id(int(name))
                    else:
                        pickcode = await get_pickcode_for_name(name)
            if not pickcode:
                return text(str(request.url), 404)
            user_agent = (request.get_first_header(b"User-agent") or b"").decode("latin-1")
            url = await get_downurl(pickcode.lower(), user_agent)

        return redirect(url)

    return app


if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError:
        from sys import executable
        from subprocess import run
        run([executable, "-m", "pip", "install", "-U", "uvicorn"], check=True)
        import uvicorn

    print(__doc__)
    app = make_application(cookies, debug=args.debug)
    uvicorn.run(
        app, 
        host=args.host, 
        port=args.port, 
        proxy_headers=True, 
        forwarded_allow_ips="*", 
    )

