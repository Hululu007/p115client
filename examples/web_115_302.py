#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 3)
__all__ = ["make_application"]
__requirements__ = ["blacksheep", "blacksheep_client_request", "cachetools", "p115client", "posixpatht", "uvicorn"]
__doc__ = """\
        \x1b[5m🚀\x1b[0m \x1b[1m115 直链服务\x1b[0m \x1b[5m🍳\x1b[0m

链接格式（每个参数都是\x1b[1;31m可选的\x1b[0m）：\x1b[4m\x1b[34mhttp://localhost:8000{\x1b[1;36mpath2\x1b[0m\x1b[4m\x1b[34m}?pickcode={\x1b[1;36mpickcode\x1b[0m\x1b[4m\x1b[34m}&id={\x1b[1;36mid\x1b[0m\x1b[4m\x1b[34m}&sha1={\x1b[1;36msha1\x1b[0m\x1b[4m\x1b[34m}&path={\x1b[1;36mpath\x1b[0m\x1b[4m\x1b[34m}&kind={\x1b[1;36mkind\x1b[0m\x1b[4m\x1b[34m}&cache={\x1b[1;36mcache\x1b[0m\x1b[4m\x1b[34m}&sign={\x1b[1;36msign\x1b[0m\x1b[4m\x1b[34m}&t={\x1b[1;36mt\x1b[0m\x1b[4m\x1b[34m}\x1b[0m

- \x1b[1;36mpickcode\x1b[0m: 文件的 \x1b[1;36mpickcode\x1b[0m，优先级高于 \x1b[1;36mid\x1b[0m
- \x1b[1;36mid\x1b[0m: 文件的 \x1b[1;36mid\x1b[0m，优先级高于 \x1b[1;36msha1\x1b[0m
- \x1b[1;36msha1\x1b[0m: 文件的 \x1b[1;36msha1\x1b[0m，优先级高于 \x1b[1;36mpath\x1b[0m
- \x1b[1;36mpath\x1b[0m: 文件的路径，优先级高于 \x1b[1;36mpath2\x1b[0m
- \x1b[1;36mpath2\x1b[0m: 文件的路径，优先级最低
- \x1b[1;36mkind\x1b[0m: 文件类型，默认为 \x1b[1mfile\x1b[0m，用于返回特定的下载链接
    - \x1b[1mfile\x1b[0m: 文件，返回普通的链接（\x1b[1;31m有\x1b[0m\x1b[1m并发数限制\x1b[0m）
    - \x1b[1mimage\x1b[0m: 图片，返回 CDN 链接（\x1b[1;32m无\x1b[0m\x1b[1m并发数限制\x1b[0m）
    - \x1b[1msubtitle\x1b[0m: 字幕，返回链接（\x1b[1;32m无\x1b[0m\x1b[1m并发数限制\x1b[0m）
- \x1b[1;36mcache\x1b[0m: 接受 \x1b[1;33m1\x1b[0m | \x1b[1;33mtrue\x1b[0m 或 \x1b[1;33m0\x1b[0m | \x1b[1;33mfalse\x1b[0m，如果为 \x1b[1;33m1\x1b[0m | \x1b[1;33mtrue\x1b[0m，则使用 \x1b[1;36mpath\x1b[0m 到 \x1b[1;36mpickcode\x1b[0m 的缓存（\x1b[1m如果有的话\x1b[0m），否则不使用（\x1b[1m即使有的话\x1b[0m）
- \x1b[1;36msign\x1b[0m: 计算方式为 \x1b[2mhashlib.sha1(bytes(f"302@115-{token}-{t}-{value}", "utf-8")).hexdigest()\x1b[0m
    - \x1b[1mtoken\x1b[0m: 命令行中所传入的 \x1b[1mtoken\x1b[0m
    - \x1b[1mt\x1b[0m: 过期时间戳（\x1b[1m超过这个时间后，链接不可用\x1b[0m）
    - \x1b[1mvalue\x1b[0m: 按顺序检查 \x1b[1;36mpickcode\x1b[0m、\x1b[1;36mid\x1b[0m、\x1b[1;36msha1\x1b[0m、\x1b[1;36mpath\x1b[0m、\x1b[1;36mpath2\x1b[0m，最先有效的那个值
- \x1b[1;36mt\x1b[0m: 链接过期时间戳，接受一个整数，只在使用签名时有效，如果不提供或者小于等于 0，则永久有效

        \x1b[5m🔨\x1b[0m 如何运行 \x1b[5m🪛\x1b[0m

请在当前工作目录下创建一个 \x1b[4m\x1b[34m115-cookies.txt\x1b[0m，并把 115 的 cookies 保存其中，格式为

    UID=...; CID=...; SEID=...

然后运行脚本（默认端口：\x1b[1;33m8000\x1b[0m，可用命令行参数 \x1b[1m-P\x1b[0m/\x1b[1m--port\x1b[0m 指定其它端口号）

    python web_115_302.py

支持对指定目录进行预热，请发送目录 id (cid) 到后台任务

    \x1b[1mPOST\x1b[0m \x1b[4m\x1b[34mhttp://localhost:8000/run?cid={cid}\x1b[0m

另外还提供了文档

    \x1b[4m\x1b[34mhttp://localhost:8000/docs\x1b[0m

或者

    \x1b[4m\x1b[34mhttp://localhost:8000/redocs\x1b[0m

再推荐一个命令行使用，用于执行 HTTP 请求的工具，类似 \x1b[1;3mwget\x1b[0m

    \x1b[4m\x1b[34mhttps://pypi.org/project/httpie/\x1b[0m
"""

if __name__ == "__main__":
    from argparse import ArgumentParser, RawTextHelpFormatter

    parser = ArgumentParser(formatter_class=RawTextHelpFormatter, description=__doc__)
    parser.add_argument("-cp", "--cookies-path", default="", help="cookies 文件保存路径，默认为当前工作目录下的 115-cookies.txt")
    parser.add_argument("-p", "--password", help="执行 POST 请求所需密码")
    parser.add_argument("-t", "--token", default="", help="用于给链接进行签名的 token，如果不提供则无签名")
    parser.add_argument("-pcs", "--path-cache-size", type=int, default=1048576, help="路径缓存的容量大小，默认值 1048576，等于 0 时关闭，小于等于 0 时不限")
    parser.add_argument("-pct", "--path-cache-ttl", type=float, default=0, help="路径缓存的存活时间，小于等于 0 或等于 inf 或 nan 时不限，默认为不限")
    parser.add_argument("-H", "--host", default="0.0.0.0", help="ip 或 hostname，默认值：'0.0.0.0'")
    parser.add_argument("-P", "--port", default=8000, type=int, help="端口号，默认值：8000")
    parser.add_argument("-v", "--version", action="store_true", help="输出版本号")

    args = parser.parse_args()
    if args.version:
        print(".".join(map(str, __version__)))
        raise SystemExit(0)

try:
    from blacksheep import json, redirect, text, Application, FromJSON, Router
    from blacksheep.client.session import ClientSession
    from blacksheep.exceptions import HTTPException
    from blacksheep.server.openapi.common import ParameterInfo
    from blacksheep.server.openapi.ui import ReDocUIProvider
    from blacksheep.server.openapi.v3 import OpenAPIHandler
    from blacksheep.server.remotes.forwarding import ForwardedHeadersMiddleware
    from blacksheep.messages import Request
    from blacksheep_client_request import request as blacksheep_request
    from cachetools import LRUCache, TTLCache
    from openapidocs.v3 import Info # type: ignore
    from p115client import P115Client, AuthenticationError, SUFFIX_TO_TYPE
    from p115client.tool.iterdir import iter_files, _iter_fs_files
    from posixpatht import dirname, escape, joins, splits
except ImportError:
    from sys import executable
    from subprocess import run
    run([executable, "-m", "pip", "install", "-U", *__requirements__], check=True)
    from blacksheep import json, redirect, text, Application, FromJSON, Router
    from blacksheep.client.session import ClientSession
    from blacksheep.exceptions import HTTPException
    from blacksheep.server.openapi.common import ParameterInfo
    from blacksheep.server.openapi.ui import ReDocUIProvider
    from blacksheep.server.openapi.v3 import OpenAPIHandler
    from blacksheep.server.remotes.forwarding import ForwardedHeadersMiddleware
    from blacksheep.messages import Request
    from blacksheep_client_request import request as blacksheep_request
    from cachetools import LRUCache, TTLCache
    from openapidocs.v3 import Info # type: ignore
    from p115client import P115Client, AuthenticationError, SUFFIX_TO_TYPE
    from p115client.tool.iterdir import iter_files, _iter_fs_files
    from posixpatht import dirname, escape, joins, splits

import errno
import logging

from asyncio import create_task, CancelledError, Queue
from collections.abc import AsyncIterator, Callable, MutableMapping
from functools import partial, update_wrapper
from hashlib import sha1 as calc_sha1
from math import inf, isinf, isnan
from pathlib import Path
from string import hexdigits
from sys import maxsize
from time import time
from typing import cast, Literal
from urllib.parse import unquote, urlsplit


def reduce_image_url_layers(url: str, /) -> str:
    if not url.startswith(("http://thumb.115.com/", "https://thumb.115.com/")):
        return url
    urlp = urlsplit(url)
    sha1 = urlp.path.rsplit("/")[-1].split("_")[0]
    return f"https://imgjump.115.com/?sha1={sha1}&{urlp.query}&size=0"


def make_application(
    cookies_path: str | Path = "", 
    password: str = "", 
    token: str = "", 
    path_cache_size: int = 1048576, 
    path_cache_ttl: int | float = 0, 
) -> Application:
    # NOTE: cookies 保存路径
    if cookies_path:
        cookies_path = Path(cookies_path)
    else:
        cookies_path = Path("115-cookies.txt")
    # NOTE: id   到 pickcode 的映射
    ID_TO_PICKCODE: MutableMapping[str, str] = LRUCache(65536)
    # NOTE: sha1 到 pickcode 的映射
    SHA1_TO_PICKCODE: MutableMapping[str, str] = LRUCache(65536)
    # NOTE: path 到 pickcode 的映射
    PATH_TO_PICKCODE: None | MutableMapping[str, str] = None
    if path_cache_size:
        if path_cache_ttl > 0 and not isinf(path_cache_ttl) and not isnan(path_cache_ttl):
            if path_cache_size > 0:
                PATH_TO_PICKCODE = TTLCache(path_cache_size, path_cache_ttl)
            else:
                PATH_TO_PICKCODE = TTLCache(maxsize, path_cache_ttl)
        elif path_cache_size > 0:
            PATH_TO_PICKCODE = LRUCache(path_cache_size)
        else:
            PATH_TO_PICKCODE = {}
    # NOTE: 缓存图片的 CDN 直链 1 小时
    IMAGE_URL_CACHE: MutableMapping[str, bytes] = TTLCache(inf, ttl=3600)
    # NOTE: 缓存字幕的 CDN 直链 1 小时
    SUBTITLE_URL_CACHE: MutableMapping[str, bytes] = TTLCache(inf, ttl=3600)
    # 排队任务（一次性运行，不在周期性运行的 cids 列表中）
    QUEUE: Queue[tuple[str, Literal[1,2,3,4,5,6,7,99]]] = Queue()
    # 执行 POST 请求时所需要携带的密码
    PASSWORD = password
    # blacksheep 应用
    app = Application(router=Router())
    # 启用文档
    docs = OpenAPIHandler(info=Info(
        title="web-115-302.py web api docs", 
        version=".".join(map(str, __version__)), 
    ))
    docs.ui_providers.append(ReDocUIProvider())
    docs.bind_app(app)
    # 日志对象
    logger = getattr(app, "logger")
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[\x1b[1m%(asctime)s\x1b[0m] (\x1b[1;36m%(levelname)s\x1b[0m) \x1b[5;31m➜\x1b[0m %(message)s"))
    logger.addHandler(handler)
    # 后台任务中，正在运行的任务
    qrunning_task = None
    # 后台任务中运行的 cid
    qcid = ""

    def redirect_exception_response(func, /):
        async def wrapper(*args, **kwds):
            try:
                return await func(*args, **kwds)
            except BaseException as e:
                if isinstance(e, HTTPException):
                    return text(f"{type(e).__module__}.{type(e).__qualname__}: {e}", e.status)
                elif isinstance(e, AuthenticationError):
                    return json(e.args[1], 401)
                elif isinstance(e, PermissionError):
                    return json(e.args[1], 403)
                elif isinstance(e, FileNotFoundError):
                    return json(e.args[1], 404)
                elif isinstance(e, (IsADirectoryError, NotADirectoryError)):
                    return json(e.args[1], 406)
                elif isinstance(e, OSError):
                    if (args := e.args) and len(args) >= 2:
                        message = args[1]
                        if isinstance(message, dict):
                            return json(message, 500)
                    return json({"state": False, "message": str(e)}, 500)
                elif isinstance(e, Exception):
                    return json({"state": False, "message": str(e)}, 503)
                raise
        return update_wrapper(wrapper, func)

    def normalize_attr(
        info: dict, 
        /, 
        dirname: str = "", 
    ) -> dict:
        """对文件信息进行规范化
        """
        if "file_id" in info or "file_name" in info:
            file_id = info.get("file_id", "")
            if file_id:
                file_id = str(file_id)
            file_name = cast(str, info["file_name"])
            pick_code = cast(str, info["pick_code"])
            if "file_sha1" in info:
                file_sha1 = info["file_sha1"]
            elif "sha1" in info:
                file_sha1 = info["sha1"]
            else:
                file_sha1 = ""
            if "origin_url" in info:
                thumb = info["origin_url"]
            elif "img_url" in info:
                thumb = info["img_url"]
            else:
                thumb = ""
        else:
            file_id = str(info["fid"])
            file_name = cast(str, info["n"])
            pick_code = cast(str, info["pc"])
            file_sha1 = cast(str, info["sha"])
            thumb = info.get("u", "")
        if file_sha1:
            SHA1_TO_PICKCODE[file_sha1] = pick_code
        if file_id:
            ID_TO_PICKCODE[file_id] = pick_code
        if PATH_TO_PICKCODE is not None and dirname:
            PATH_TO_PICKCODE[dirname + "/" + escape(file_name)] = pick_code
        attr = {"id": file_id, "name": file_name, "pickcode": pick_code, "sha1": file_sha1}
        if thumb:
            attr["thumb"] = IMAGE_URL_CACHE[pick_code] = bytes(reduce_image_url_layers(thumb), "utf-8")
        return attr

    async def load_files(
        cid: int | str = "0", 
        /, 
        type: Literal[1, 2, 3, 4, 5, 6, 7, 99] = 99, 
    ) -> int:
        """批量拉取文件信息，以构建缓存
        """
        client = app.services.resolve(ClientSession)
        p115client = app.services.resolve(P115Client)
        with_path = PATH_TO_PICKCODE is not None
        count = 0
        async for attr in iter_files(
            p115client, 
            int(cid), 
            type=type, 
            async_=True, 
            with_path=with_path, 
            request=blacksheep_request, 
            session=client, 
        ):
            pickcode = attr["pickcode"]
            ID_TO_PICKCODE[str(attr["id"])] = pickcode
            SHA1_TO_PICKCODE[attr["sha1"]] = pickcode
            if with_path:
                PATH_TO_PICKCODE[attr["path"]] = pickcode # type: ignore
            if thumb := attr.get("thumb"):
                IMAGE_URL_CACHE[pickcode] = bytes(reduce_image_url_layers(thumb), "utf-8")
            count += 1
        return count

    async def queue_load_files():
        nonlocal qrunning_task, qcid
        while True:
            qcid, type = await QUEUE.get()
            this_start = time()
            qrunning_task = create_task(load_files(qcid, type=type))
            try:
                logger.info(f"background task start: cid={qcid}")
                count = await qrunning_task
            except CancelledError as e:
                logger.warning(f"task cancelled cid={qcid}")
                if not e.args or e.args[0] == "shutdown":
                    return
                cmd = e.args[0]
                if cmd == "sleep":
                    break
            except Exception:
                logger.exception(f"error occurred while loading cid={qcid}")
            else:
                logger.info(f"successfully loaded cid={qcid}, {count} files, {time() - this_start:.6f} seconds")
            finally:
                qcid = ""
                qrunning_task = None
                QUEUE.task_done()

    def iterdir(
        client: P115Client, 
        cid: str, 
        /, 
        only_dirs_or_files: None | bool = None, 
        request: None | Callable = None, 
    ) -> AsyncIterator[dict]:
        """获取目录中的文件信息迭代器
        """
        payload = {"cid": cid, "cur": 1, "fc_mix": 1, "show_dir": 1, "limit": 10_000}
        only_dirs = only_dirs_or_files
        if only_dirs is None:
            only_dirs = False
        elif only_dirs:
            payload["fc_mix"] = 0
        else:
            payload["show_dir"] = 0
        return _iter_fs_files(client, payload, only_dirs=only_dirs, async_=True, request=request)

    async def get_attr_by_id(
        client: P115Client, 
        id: str, 
        /, 
        request: None | Callable = None, 
    ) -> dict:
        """获取 id 对应的文件的 信息
        """
        resp = await client.fs_file(id, async_=True, request=request)
        if not resp["state"]:
            resp["file_id"] = id
            raise FileNotFoundError(errno.ENOENT, resp)
        info = resp["data"][0]
        if "fid" not in info:
            raise FileNotFoundError(
                errno.EISDIR, 
                {"state": False, "message": "not a file", "file_id": id}, 
            )
        return normalize_attr(info)

    async def get_pickcode_by_id(
        client: P115Client, 
        id: str, 
        /, 
        request: None | Callable = None, 
    ) -> str:
        """获取 id 对应的文件的 pickcode
        """
        if pickcode := ID_TO_PICKCODE.get(id):
            return pickcode
        attr = await get_attr_by_id(client, id, request=request)
        return attr["pickcode"]

    async def get_pickcode_by_sha1(
        client: P115Client, 
        sha1: str, 
        /, 
        request: None | Callable = None, 
    ) -> str:
        """获取 sha1 对应的文件的 pickcode
        """
        if pickcode := SHA1_TO_PICKCODE.get(sha1):
            return pickcode
        resp = await client.fs_shasearch(sha1, async_=True, request=request)
        if not resp["state"]:
            raise FileNotFoundError(
                errno.ENOENT, 
                {"state": False, "message": "no such sha1", "sha1": sha1}, 
            )
        info = resp["data"]
        info["file_sha1"] = sha1
        return normalize_attr(info)["pickcode"]

    async def get_pickcode_by_path(
        client: P115Client, 
        path: str, 
        /, 
        request: None | Callable = None, 
        cache: bool = True, 
    ) -> str:
        """获取路径对应的文件的 pickcode
        """
        error = FileNotFoundError(
            errno.ENOENT, 
            {"state": False, "message": "no such path to file", "path": path}, 
        )
        patht, _ = splits("/" + path)
        if len(patht) == 1:
            raise error
        path = joins(patht)
        if (
            cache and 
            PATH_TO_PICKCODE is not None and
            (pickcode := PATH_TO_PICKCODE.get(path))
        ):
            return pickcode
        i = 1
        if len(patht) > 2:
            for i in range(1, len(patht) - 1):
                name = patht[i]
                if "/" in name:
                    break
            else:
                i += 1
        if i == 1:
            cid = "0"
            dirname = "/"
        else:
            dirname = "/".join(patht[:i])
            resp = await client.fs_dir_getid(dirname, async_=True, request=request)
            if not (resp["state"] and (cid := resp["id"])):
                raise error
        for name in patht[i:-1]:
            async for info in iterdir(client, cid, only_dirs_or_files=True, request=request):
                if info["n"] == name:
                    cid = info["pid"]
                    dirname += "/" + escape(name)
                    break
            else:
                raise error
        name = patht[-1]
        async for info in iterdir(client, cid, only_dirs_or_files=False, request=request):
            attr = normalize_attr(info, dirname)
            if attr["name"] == name:
                return attr["pickcode"]
        else:
            raise error

    async def get_url(
        client: P115Client, 
        pickcode: str, 
        /, 
        user_agent: str = "", 
        request: None | Callable = None, 
    ) -> str:
        """获取文件的下载链接
        """
        resp = await client.download_url_app(
            pickcode, 
            headers={"User-Agent": user_agent}, 
            async_=True, 
            request=request, 
        )
        if not resp["state"]:
            resp["pickcode"] = pickcode
            raise FileNotFoundError(errno.ENOENT, resp)
        fid, info = next(iter(resp["data"].items()))
        pickcode = info["pick_code"]
        ID_TO_PICKCODE[fid] = SHA1_TO_PICKCODE[info["sha1"]] = pickcode
        if SUFFIX_TO_TYPE.get(info["file_name"].lower()) == 2:
            IMAGE_URL_CACHE.setdefault(pickcode, b"")
        return info["url"]["url"]

    async def get_image_url(
        client: P115Client, 
        pickcode: str, 
        /, 
        request: None | Callable = None, 
    ) -> bytes:
        """获取图片的 cdn 链接
        """
        if url := IMAGE_URL_CACHE.get(pickcode):
            return url
        resp = await client.fs_image(pickcode, async_=True, request=request)
        if not resp["state"]:
            raise FileNotFoundError(
                errno.ENOENT, 
                {"state": False, "message": "no such pickcode to image", "pickcode": pickcode}, 
            )
        return normalize_attr(resp["data"])["thumb"]

    async def get_subtitle_url(
        client: P115Client, 
        pickcode: str, 
        /, 
        request: None | Callable = None, 
    ) -> bytes:
        """获取字幕的下载链接
        """
        if url := SUBTITLE_URL_CACHE.get(pickcode):
            return url
        resp = await client.fs_video_subtitle(pickcode, async_=True, request=request)
        if not resp["state"]:
            raise FileNotFoundError(
                errno.ENOENT, 
                {"state": False, "message": "no such pickcode to subtitle", "pickcode": pickcode}, 
            )
        dir_ = ""
        if PATH_TO_PICKCODE is not None:
            try:
                for k, v in PATH_TO_PICKCODE.items():
                    if v == pickcode:
                        dir_ = dirname(k)
                        break
            except RuntimeError:
                pass
        url = b""
        for info in resp["data"]["list"]:
            if pickcode2 := info.get("pick_code"):
                attr = normalize_attr(info, dir_)
                url2 = SUBTITLE_URL_CACHE[pickcode2] = bytes(info["url"], "utf-8")
                if pickcode == pickcode2:
                    url = url2
        if not url:
            raise FileNotFoundError(
                errno.ENOENT, 
                {"state": False, "message": "no such pickcode to subtitle", "pickcode": pickcode}, 
            )
        return url

    @app.on_middlewares_configuration
    def configure_forwarded_headers(app: Application):
        app.middlewares.insert(0, ForwardedHeadersMiddleware(accept_only_proxied_requests=False))

    @app.lifespan
    async def register_client(app: Application):
        async with ClientSession(follow_redirects=False) as client:
            app.services.register(ClientSession, instance=client)
            yield

    @app.lifespan
    async def register_p115client(app: Application):
        client = P115Client(
            cookies_path, 
            app="harmony", 
            check_for_relogin=True, 
        )
        async with client.async_session:
            app.services.register(P115Client, instance=client)
            yield

    @app.lifespan
    async def start_tasks(app: Application):
        queue_task = create_task(queue_load_files())
        try:
            yield
        finally:
            queue_task.cancel("shutdown")

    @app.router.route("/", methods=["GET", "HEAD"])
    @app.router.route("/{path:path2}", methods=["GET", "HEAD"])
    @redirect_exception_response
    async def get_download_url(
        request: Request, 
        client: ClientSession, 
        p115client: P115Client, 
        pickcode: str = "", 
        id: str = "", 
        sha1: str = "", 
        path: str = "", 
        path2: str = "", 
        kind: str = "file", 
        cache: bool = True, 
        sign: str = "", 
        t: int = 0, 
    ):
        """获取文件的下载链接

        :param pickcode: 文件或目录的 pickcode，优先级高于 id
        :param id: 文件的 id，优先级高于 sha1
        :param sha1: 文件的 sha1，优先级高于 path
        :param path: 文件的路径，优先级高于 path2
        :param path2: 文件的路径，这个直接在接口路径之后，不在查询字符串中
        :param kind: 文件类型，默认为 **file**，用于返回特定的下载链接
            <br />- **file**&colon; 文件，返回普通的链接（有并发数限制）
            <br />- **image**&colon; 图片，返回 CDN 链接（无并发数限制）
            <br />- **subtitle**&colon; 字幕，返回链接（无并发数限制）
        :param cache: 是否使用 路径 到 pickcode 的缓存
        :param sign: 签名，计算方式为 `hashlib.sha1(bytes(f"302@115-{token}-{t}-{value}", "utf-8")).hexdigest()`
            <br />- **token**&colon; 命令行中所传入的 token
            <br />- **t**&colon; 过期时间戳（超过这个时间后，链接不可用）
            <br />- **value**&colon; 按顺序检查 `pickcode`、`id`、`sha1`、`path`、`path2`，最先有效的那个值
        :param t: 过期时间戳
        """
        def check_sign(value, /):
            if not token:
                return None
            if sign != calc_sha1(bytes(f"302@115-{token}-{t}-{value}", "utf-8")).hexdigest():
                return json({"state": False, "message": "invalid sign"}, 403)
            elif t > 0 and t <= time():
                return json({"state": False, "message": "url was expired"}, 401)
        do_request = partial(blacksheep_request, session=client)
        if pickcode := pickcode.strip().lower():
            if resp := check_sign(pickcode):
                return resp
            if not pickcode.isalnum():
                return json({"state": False, "message": f"bad pickcode: {pickcode!r}"}, 400)
        elif id := id.strip():
            if resp := check_sign(id):
                return resp
            if id.startswith("0") or not id.isdecimal():
                return json({"state": False, "message": f"bad id: {id!r}"}, 400)
            pickcode = await get_pickcode_by_id(p115client, id, do_request)
        elif sha1 := sha1.strip().upper():
            if resp := check_sign(sha1):
                return resp
            if len(sha1) != 40 or sha1.strip(hexdigits):
                return json({"state": False, "message": f"bad sha1: {sha1!r}"}, 400)
            pickcode = await get_pickcode_by_sha1(p115client, sha1, do_request)
        else:
            value = unquote(path) or path2
            if not value:
                return json({"state": False, "message": "no query value"}, 400)
            if resp := check_sign(value):
                return resp
            pickcode = await get_pickcode_by_path(p115client, value, do_request, cache)
        match kind:
            case "image":
                return redirect(await get_image_url(p115client, pickcode, do_request))
            case "subtitle":
                return redirect(await get_subtitle_url(p115client, pickcode, do_request))
            case _:
                user_agent = (request.get_first_header(b"User-agent") or b"").decode("latin-1")
                return redirect(await get_url(p115client, pickcode, user_agent, do_request))

    @app.router.route("/run", methods=["POST"])
    async def do_run(request: Request, cid: str = "0", type: int = 2, password: str = ""):
        """运行后台（预热）任务

        :param cid: 把此 cid 加入后台（预热）任务（默认值 0）
        :param type: 文件类型（默认值 2）
              <br />- **1**&colon; 文档
              <br />- **2**&colon; 图片
              <br />- **3**&colon; 音频
              <br />- **4**&colon; 视频
              <br />- **5**&colon; 压缩包
              <br />- **6**&colon; 应用
              <br />- **7**&colon; 书籍
              <br />- **99**&colon; 任意文件
        :param password: 口令
        """
        if PASSWORD and PASSWORD != password:
            return json({"state": False, "message": "password does not match"}, 401)
        if type not in range(1, 8):
            type = 99
        QUEUE.put_nowait((cid, type)) # type: ignore
        return json({"state": True, "message": "ok"})

    @app.router.route("/skip", methods=["POST"])
    async def do_qskip(request: Request, cid: str = "0", password: str = ""):
        """跳过当前后台（预热）任务中正在运行的任务

        :param cid: 如果提供，则仅当正在运行的 cid 等于此 cid 时，才会取消任务
        :param password: 口令
        """
        if PASSWORD and PASSWORD != password:
            return json({"state": False, "message": "password does not match"}, 401)
        try:
            if not cid or cid == qcid:
                qrunning_task.cancel("skip") # type: ignore
        except AttributeError:
            pass
        return json({"state": True, "message": "ok"})

    @app.router.route("/running", methods=["POST"])
    async def get_batch_task_running(request: Request, password: str = ""):
        """批量任务中，是否有任务在运行中

        :param password: 口令
        """
        if PASSWORD and PASSWORD != password:
            return json({"state": False, "message": "password does not match"}, 401)
        if qrunning_task is None:
            return json({"state": True, "message": "ok", "value": False})
        else:
            return json({"state": True, "message": "ok", "value": True, "cid": qcid})

    @app.router.route("/cookies", methods=["POST"])
    async def set_cookies(request: Request, p115client: P115Client, password: str = "", body: None | FromJSON[dict] = None):
        """更新 cookies

        :param password: 口令
        :param body: 请求体为 json 格式 <code>{"value"&colon; "新的 cookies"}</code>
        """
        if PASSWORD and PASSWORD != password:
            return json({"state": False, "message": "password does not match"}, 401)
        if body:
            payload = body.value
            cookies = payload.get("value")
            if isinstance(cookies, str):
                try:
                    p115client.cookies = cookies
                    return json({"state": True, "message": "ok"})
                except Exception as e:
                    return json({"state": False, "message": str(e)})
        return json({"state": True, "message": "skip"})

    return app


if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError:
        from sys import executable
        from subprocess import run
        run([executable, "-m", "pip", "install", "-U", "uvicorn"], check=True)
        import uvicorn

    app = make_application(
        cookies_path=args.cookies_path, 
        password=args.password, 
        token=args.token, 
        path_cache_size=args.path_cache_size, 
        path_cache_ttl=args.path_cache_ttl, 
    )
    print(__doc__)
    uvicorn.run(
        app=app, 
        host=args.host, 
        port=args.port, 
        proxy_headers=True, 
        forwarded_allow_ips="*", 
    )

# TODO: 提供接口，可用于增删改查 PATH_TO_PICKCODE 的字典，支持使用正则表达式、通配符等，如果为 None，则报错（未开启路径缓存）
# TODO: 提供接口，可以修改 path_cache_size 和 path_cache_ttl（修改后可能导致部分数据丢失）
# TODO: 增加接口，用于一次性获取多个 id 对应的 pickcode
# TODO: 增加接口，支持一次性查询多个直链（需要使用 pickcode 或 id 才行）

