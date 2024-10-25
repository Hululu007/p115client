#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 1)
__doc__ = "115 302 迷你版，仅支持用 pickcode、id 或 sha1 查询（排名越前，优先级越高）"
__requirements__ = ["blacksheep", "p115client", "uvicorn"]

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
    from blacksheep import route, redirect, text, Application, Request
    from p115client import P115Client
except ImportError:
    from sys import executable
    from subprocess import run
    run([executable, "-m", "pip", "install", "-U", *__requirements__], check=True)
    from blacksheep import route, redirect, text, Application, Request
    from p115client import P115Client

from pathlib import Path


if __name__ == "__main__":
    cookies_path = Path(args.cookies_path or "115-cookies.txt")
else:
    cookies_path = Path("115-cookies.txt")
client = P115Client(cookies_path, app="harmony", check_for_relogin=True)

app = Application()
id_to_pickcode: dict[int, str] = {}
sha1_to_pickcode: dict[str, str] = {}


@route("/", methods=["GET", "HEAD"])
@route("/<path:name>", methods=["GET", "HEAD"])
async def index(
    request: Request, 
    pickcode: str = "", 
    id: int = 0, 
    sha1: str = "", 
):
    if pickcode := pickcode.strip():
        pass
    elif id and not (pickcode := id_to_pickcode.get(id, "")):
        resp = await client.fs_file_skim(id, async_=True)
        if resp and resp["state"]:
            pickcode = id_to_pickcode[id] = resp["data"][0]["pick_code"]
    elif (sha1 := sha1.strip()) and not (pickcode := sha1_to_pickcode.get(sha1, "")):
        resp = await client.fs_shasearch(sha1, async_=True)
        if resp and resp["state"]:
            pickcode = sha1_to_pickcode[sha1] = resp["data"]["pick_code"]
    if not pickcode:
        return text("Bad Request: Missing or bad query parameter: `pickcode`, `id` nor `sha1`", 400)
    user_agent = request.headers.get_first(b"user-agent") or b""
    try:
        return redirect(await client.download_url(
            pickcode, 
            headers={"user-agent": user_agent.decode("latin-1")}, 
            async_=True, 
        ))
    except FileNotFoundError:
        pass
    return text(f"bad pickcode: {pickcode!r}", 400)


if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError:
        from sys import executable
        from subprocess import run
        run([executable, "-m", "pip", "install", "-U", "uvicorn"], check=True)
        import uvicorn
    uvicorn.run(app=app, host=args.host, port=args.port)

