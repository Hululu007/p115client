#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 2)
__doc__ = "115 302 迷你版，仅支持用 pickcode、id 或 sha1 查询（排名越前，优先级越高）"
__requirements__ = ["blacksheep", "cachetools", "p115client", "uvicorn"]

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

try:
    from blacksheep import route, redirect, json, text, Application, Request
    from cachetools import TTLCache
    from p115client import P115Client, P115OSError
except ImportError:
    from sys import executable
    from subprocess import run
    run([executable, "-m", "pip", "install", "-U", *__requirements__], check=True)
    from blacksheep import route, redirect, json, text, Application, Request
    from cachetools import TTLCache
    from p115client import P115Client, P115OSError

from pathlib import Path
from string import hexdigits


if __name__ == "__main__":
    cookies_path = Path(args.cookies_path or "115-cookies.txt")
else:
    cookies_path = Path("115-cookies.txt")
client = P115Client(cookies_path, app="harmony", check_for_relogin=True)

app = Application()
# NOTE: id 到 pickcode 的映射
ID_TO_PICKCODE: dict[int, str] = {}
# NOTE: sha1 到 pickcode 的映射
SHA1_TO_PICKCODE: dict[str, str] = {}
# NOTE: 限制请求频率，以一组请求信息为 key，0.5 秒内相同的 key 只放行一个
URL_COOLDOWN: TTLCache[tuple, None] = TTLCache(1024, ttl=0.5)
# NOTE: 下载链接缓存，以减少接口调用频率，只需缓存很短时间
URL_CACHE: TTLCache[tuple, str] = TTLCache(64, ttl=1)


@route("/", methods=["GET", "HEAD"])
@route("/<path:name>", methods=["GET", "HEAD"])
async def index(
    request: Request, 
    pickcode: str = "", 
    id: int = 0, 
    sha1: str = "", 
):
    if pickcode := pickcode.strip().lower():
        if not pickcode.isalnum():
            return text(f"bad pickcode: {pickcode!r}", 400)
    elif id and not (pickcode := ID_TO_PICKCODE.get(id, "")):
        resp = await client.fs_file_skim(id, async_=True)
        if resp and resp["state"]:
            pickcode = ID_TO_PICKCODE[id] = resp["data"][0]["pick_code"]
    elif sha1 := sha1.strip().upper():
        if len(sha1) != 40 or sha1.strip(hexdigits):
            return text(f"bad sha1: {sha1!r}", 400)
        if not (pickcode := SHA1_TO_PICKCODE.get(sha1, "")):
            resp = await client.fs_shasearch(sha1, async_=True)
            if resp and resp["state"]:
                pickcode = SHA1_TO_PICKCODE[sha1] = resp["data"]["pick_code"]
    if not pickcode:
        return text("Bad Request: Missing or bad query parameter: `pickcode`, `id` nor `sha1`", 400)
    user_agent = (request.get_first_header(b"User-agent") or b"").decode("latin-1")
    bytes_range = (request.get_first_header(b"Range") or b"").decode("latin-1")
    url = ""
    if bytes_range and not user_agent.startswith(("VLC/", "OPlayer/")):
        remote_addr = request.original_client_ip
        cooldown_key = (pickcode, remote_addr, user_agent, bytes_range)
        if cooldown_key in URL_COOLDOWN:
            return text("too many requests", 429)
        URL_COOLDOWN[cooldown_key] = None
        key = (pickcode, remote_addr, user_agent)
        url = URL_CACHE.get(key, "")
    if not url:
        try:
            url = await client.download_url(
                pickcode, 
                headers={"user-agent": user_agent}, 
                async_=True, 
            )
        except P115OSError as e:
            return json(e.args[1], 500)
        except (FileNotFoundError, IsADirectoryError) as e:
            return json(e.args[1], 404)
    return redirect(url)


if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError:
        from sys import executable
        from subprocess import run
        run([executable, "-m", "pip", "install", "-U", "uvicorn"], check=True)
        import uvicorn
    uvicorn.run(app=app, host=args.host, port=args.port)

