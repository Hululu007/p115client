#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 3)
__licence__ = "GPLv3 <https://www.gnu.org/licenses/gpl-3.0.txt>"
__doc__ = "115 302 迷你版，仅支持用 pickcode、id 或 sha1 查询"
__requirements__ = ["blacksheep", "diskcache", "p115client", "uvicorn"]

if __name__ == "__main__":
    from argparse import ArgumentParser, RawTextHelpFormatter

    parser = ArgumentParser(description=__doc__, formatter_class=RawTextHelpFormatter)
    parser.add_argument("-c", "--cookies", default="", help="cookies 字符串，优先级高于 -cp/--cookies-path")
    parser.add_argument("-cp", "--cookies-path", help="cookies 文件保存路径，默认为当前工作目录下的 115-cookies.txt")
    parser.add_argument("-H", "--host", default="0.0.0.0", help="ip 或 hostname，默认值：'0.0.0.0'")
    parser.add_argument("-P", "--port", default=8000, type=int, help="端口号，默认值：8000")
    parser.add_argument("-l", "--license", action="store_true", help="输出授权信息")
    parser.add_argument("-v", "--version", action="store_true", help="输出版本号")
    args = parser.parse_args()
    if args.version:
        print(".".join(map(str, __version__)))
        raise SystemExit(0)
    if args.license:
        print(__licence__)
        raise SystemExit(0)

try:
    from blacksheep import route, redirect, json, text, Application, Request
    from blacksheep.server.compression import use_gzip_compression
    from blacksheep.server.remotes.forwarding import ForwardedHeadersMiddleware
    from diskcache import Cache
    from p115client import P115Client, P115OSError
except ImportError:
    from sys import executable
    from subprocess import run
    run([executable, "-m", "pip", "install", "-U", *__requirements__], check=True)
    from blacksheep import route, redirect, json, text, Application, Request
    from blacksheep.server.compression import use_gzip_compression
    from blacksheep.server.remotes.forwarding import ForwardedHeadersMiddleware
    from diskcache import Cache
    from p115client import P115Client, P115OSError

from collections.abc import MutableMapping
from pathlib import Path
from string import hexdigits


if "__del__" not in Cache.__dict__:
    setattr(Cache, "__del__", Cache.close)

if __name__ != "__main__":
    cookies: str | Path = Path("115-cookies.txt")
elif not (cookies := args.cookies.strip()):
    cookies = Path(args.cookies_path or "115-cookies.txt")
client = P115Client(cookies, app="alipaymini", check_for_relogin=True)

app = Application()
use_gzip_compression(app)
ID_TO_PICKCODE: MutableMapping[int, str] = Cache(f"115-{client.user_id}-id2pc")
SHA1_TO_PICKCODE: MutableMapping[str, str] = Cache(f"115-{client.user_id}-sha2pc")


@app.on_middlewares_configuration
def configure_forwarded_headers(app: Application):
    app.middlewares.insert(0, ForwardedHeadersMiddleware(accept_only_proxied_requests=False))


@route("/", methods=["GET", "HEAD"])
@route("/<path:name>", methods=["GET", "HEAD"])
async def index(
    request: Request, 
    pickcode: str = "", 
    id: int = 0, 
    sha1: str = "", 
):
    if pickcode := pickcode.strip().lower():
        if not (len(pickcode) == 17 and pickcode.isalnum()):
            return text(f"bad pickcode: {pickcode!r}", 400)
    elif id and not (pickcode := ID_TO_PICKCODE.get(id, "")):
        resp = await client.fs_file_skim(id, async_=True)
        if not (resp and resp["state"]):
            return json(resp, 404)
        pickcode = ID_TO_PICKCODE[id] = resp["data"][0]["pick_code"]
    elif sha1 := sha1.strip().upper():
        if len(sha1) != 40 or sha1.strip(hexdigits):
            return text(f"bad sha1: {sha1!r}", 400)
        if not (pickcode := SHA1_TO_PICKCODE.get(sha1, "")):
            resp = await client.fs_shasearch(sha1, async_=True)
            if not (resp and resp["state"]):
                return json(resp, 404)
            pickcode = SHA1_TO_PICKCODE[sha1] = resp["data"]["pick_code"]
    else:
        return text(str(request.url), 404)
    resp = await client.download_url_app(
        pickcode, 
        app="android", 
        headers={"user-agent": (request.get_first_header(b"User-agent") or b"").decode("latin-1")}, 
        async_=True, 
    )
    if not resp["state"]:
        return json(resp, 404)
    return redirect(resp["data"]["url"])


if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError:
        from sys import executable
        from subprocess import run
        run([executable, "-m", "pip", "install", "-U", "uvicorn"], check=True)
        import uvicorn

    uvicorn.run(
        app, 
        host=args.host, 
        port=args.port, 
        proxy_headers=True, 
        forwarded_allow_ips="*", 
    )

# TODO: 数据缓存到本地，使用 sqlite
# TODO: 要有 tiny 版的所有功能
# TODO: 这个完成后，或许可以把 video 版进行移除
# TODO: 增加后台任务，以更新数据库，主要是更新名字

