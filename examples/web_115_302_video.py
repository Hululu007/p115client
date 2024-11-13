#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 5)
__all__ = ["make_application"]
__doc__ = """\
        \x1b[5m🚄\x1b[0m \x1b[1m115 302 服务(针对视频)\x1b[0m \x1b[5m🌊\x1b[0m

\x1b[1mTIPS\x1b[0m: 请在当前工作目录下，创建一个 \x1b[1;4m\x1b[34m115-cookies.txt\x1b[0m 文件，并写入 cookies
      如果没有，则会自动创建，并要求你扫码，默认自动绑定到 alipaymini 端（支付宝小程序）

此程序用于请求视频文件的直链，支持 2 种调用方式

1. 以视频的文件名（仅仅是文件名，而不是完整路径）获取直链

    \x1b[4m\x1b[34mhttp://localhost:8000/video.mp4\x1b[0m

2. 以查询参数 pickcode、id、sha1 或 path（不推荐） 获取直链（这种方式可以获取任何文件的直链，不限于视频）

    \x1b[4m\x1b[34mhttp://localhost:8000?pickcode=xxxxx\x1b[0m

如果视频的文件名不在缓存中，则第 1 种调用方式会返回 404 响应。因此如果要用文件名来获取缓存，请先等缓存第一次构建完，再进行使用。
🚨 请确保那些指定目录下的视频文件的名字各不相同。

程序启动过后，会启动两种类型的后台任务，以更新缓存：

1. 批量任务：

    会周期性地拉取一些指定目录下的所有视频文件的 名字 和 pickcode，并保存到缓存中。批量任务可以被取消。

2. 队列任务：

    会从队列中逐个获取目录 id，并拉取此目录下的所有视频文件的 名字 和 pickcode，保存到缓存中。队列任务不可被取消。

另外提供了一些接口用于设置 cookies、添加增删查批量任务、添加队列任务等，具体请访问了解

    \x1b[4m\x1b[34mhttp://localhost:8000/docs\x1b[0m

或者

    \x1b[4m\x1b[34mhttp://localhost:8000/redocs\x1b[0m

再推荐一个命令行使用，用于执行 HTTP 请求的工具，类似 \x1b[1;3mwget\x1b[0m

    \x1b[4m\x1b[34mhttps://pypi.org/project/httpie/\x1b[0m
"""
__requirements__ = ["blacksheep", "blacksheep_client_request", "cachetools", "p115client", "uvicorn"]

if __name__ == "__main__":
    from argparse import ArgumentParser, RawTextHelpFormatter

    parser = ArgumentParser(formatter_class=RawTextHelpFormatter, description=__doc__)
    parser.add_argument("-c", "--cids", metavar="cid", default=["0"], nargs="*", help="待拉取的目录 id，可以传多个，如果不传，默认是根目录")
    parser.add_argument("-i", "--interval", default=30, type=float, help="前一批任务（拉完所有 cids 算一批）开始拉取，到下一批任务拉取开始，中间至少间隔的秒数，如果时间超过，则立即开始下一批，如果传入 inf 则永久睡眠，默认为 30 秒")
    parser.add_argument("-f", "--store-file", help="缓存到文件的路径，如果不提供，则在内存中（程序关闭后销毁）")
    parser.add_argument("-cp", "--cookies-path", default="", help="cookies 文件保存路径，默认为当前工作目录下的 115-cookies.txt")
    parser.add_argument("-p", "--password", help="执行 POST 请求所需密码")
    parser.add_argument("-t", "--token", default="", help="用于给链接进行签名的 token，如果不提供则无签名")
    parser.add_argument("-H", "--host", default="0.0.0.0", help="ip 或 hostname，默认值：'0.0.0.0'")
    parser.add_argument("-P", "--port", default=8000, type=int, help="端口号，默认值：8000")
    parser.add_argument("-v", "--version", action="store_true", help="输出版本号")

    args = parser.parse_args()
    if args.version:
        print(".".join(map(str, __version__)))
        raise SystemExit(0)

try:
    from p115client import P115Client, P115OSError
    from p115.tool import get_id_to_path
    from blacksheep import json, redirect, text, Application, FromJSON, Request, Router
    from blacksheep.client import ClientSession
    from blacksheep.server.openapi.common import ParameterInfo
    from blacksheep.server.openapi.ui import ReDocUIProvider
    from blacksheep.server.openapi.v3 import OpenAPIHandler
    from blacksheep.server.remotes.forwarding import ForwardedHeadersMiddleware
    from blacksheep_client_request import request as blacksheep_request
    from cachetools import TTLCache
    from openapidocs.v3 import Info
except ImportError:
    from sys import executable
    from subprocess import run
    run([executable, "-m", "pip", "install", "-U", *__requirements__], check=True)
    from p115client import P115Client, P115OSError
    from p115.tool import get_id_to_path
    from blacksheep import json, redirect, text, Application, FromJSON, Request, Router
    from blacksheep.client import ClientSession
    from blacksheep.server.openapi.common import ParameterInfo
    from blacksheep.server.openapi.ui import ReDocUIProvider
    from blacksheep.server.openapi.v3 import OpenAPIHandler
    from blacksheep.server.remotes.forwarding import ForwardedHeadersMiddleware
    from blacksheep_client_request import request as blacksheep_request
    from cachetools import TTLCache
    from openapidocs.v3 import Info # type: ignore

import logging

from asyncio import create_task, sleep, CancelledError, Queue
from collections.abc import Iterable, Iterator, MutableMapping, Sequence
from functools import partial
from hashlib import sha1 as calc_sha1
from math import isinf, isnan, nan
from pathlib import Path
from string import hexdigits
from time import time
from typing import cast
from urllib.parse import unquote


def make_application(
    cids: int | str | Iterable[int | str] = "0", 
    interval: int | float = 5, 
    store_file: str = "", 
    password: str = "", 
    token: str = "", 
    cookies_path: str | Path = "", 
) -> Application:
    # NOTE: cookies 保存路径
    if cookies_path:
        cookies_path = Path(cookies_path)
    else:
        cookies_path = Path("115-cookies.txt")
    # NOTE: id 到 pickcode 的映射
    ID_TO_PICKCODE: dict[str, str] = {}
    # NOTE: sha1 到 pickcode 的映射
    SHA1_TO_PICKCODE: dict[str, str] = {}
    # NOTE: 限制请求频率，以一组请求信息为 key，0.5 秒内相同的 key 只放行一个
    URL_COOLDOWN: MutableMapping[tuple, None] = TTLCache(1024, ttl=0.5)
    # NOTE: 下载链接缓存，以减少接口调用频率，只需缓存很短时间
    URL_CACHE: MutableMapping[tuple, str] = TTLCache(64, ttl=1)
    # NOTE: 用来保存【视频名称】对应的【pickcode】
    if store_file:
        from shelve import open as open_shelve
        NAME_TO_PICKCODE: MutableMapping[str, str] = open_shelve(store_file)
    else:
        NAME_TO_PICKCODE = {}
    # NOTE: 用来保存所有需要拉取的目录 id，如果某个目录 id 在其中的另一个之中，会被短时间内重复拉取
    if isinstance(cids, (int, str)):
        CIDS = {str(cids)}
    else:
        CIDS = set(map(str, cids))
    # NOTE: 用来保存【目录 id】对应的【目录里面最近一条视频文件的更新时间】
    MAX_MTIME_MAP: dict[str, str] = {}
    # NOTE: 执行 POST 请求时所需要携带的密码
    PASSWORD = password
    # NOTE: 排队任务（一次性运行，不在周期性运行的 cids 列表中）
    QUEUE: Queue[str] = Queue()
    # NOTE: blacksheep 应用
    app = Application(router=Router())
    # NOTE: 启用文档
    docs = OpenAPIHandler(info=Info(
        title="video-115-302.py web api docs", 
        version=".".join(map(str, __version__)), 
    ))
    docs.ui_providers.append(ReDocUIProvider())
    docs.bind_app(app)
    # NOTE: 日志对象
    logger = getattr(app, "logger")
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[\x1b[1m%(asctime)s\x1b[0m] (\x1b[1;36m%(levelname)s\x1b[0m) \x1b[5;31m➜\x1b[0m %(message)s"))
    logger.addHandler(handler)
    # 批量任务中，正在运行的任务
    running_task = None
    # 批量任务中，正在休眠
    waiting_task = None
    # 队列任务中，正在运行的任务
    qrunning_task = None
    # 批量任务中运行的 cid
    bcid = ""
    # 队列任务中运行的 cid
    qcid = ""

    def iter_cids() -> Iterator[str]:
        s: set[str] = set()
        add_cid = s.add
        cids: Iterable[str] = tuple(CIDS)
        while cids:
            for cid in cids:
                if cid in CIDS:
                    yield cid
                    add_cid(cid)
            cids = CIDS - s

    async def load_videos(cid: int | str = 0, /) -> int:
        "加载一个目录中的所有视频的 名字 和 pickcode 到缓存"
        client = app.services.resolve(ClientSession)
        p115client = app.services.resolve(P115Client)
        fs_files = partial(p115client.fs_files_app, request=blacksheep_request, session=client, async_=True)
        cid = str(cid)
        last_max_mtime = MAX_MTIME_MAP.get(cid, "0")
        page_size = 10_000 if last_max_mtime == "0" else 32
        payload = {
            "asc": 0, "cid": cid, "count_folders": 0, "cur": 0, "limit": page_size, 
            "o": "user_utime", "offset": 0, "show_dir": 0, "type": 4, 
        }
        resp = await fs_files(payload) # type: ignore
        if (not resp["state"] or 
            cid != "0" and resp["path"][-1]["cid"] != cid or 
            resp["count"] == 0):
            return 0
        this_max_mtime = resp["data"][0]["upt"]
        if last_max_mtime >= this_max_mtime:
            return 0
        count = 0
        payload["limit"] = 10_000
        while True:
            for info in resp["data"]:
                mtime = info["upt"]
                if mtime <= last_max_mtime:
                    MAX_MTIME_MAP[cid] = this_max_mtime
                    return count
                NAME_TO_PICKCODE[info["fn"]] = info["pc"]
                count += 1
            payload["offset"] += len(resp["data"]) # type: ignore
            if payload["offset"] >= resp["count"]:
                break
            resp = await fs_files(payload) # type: ignore
            if (not resp["state"] or 
                cid != "0" and resp["path"][-1]["cid"] != cid or 
                payload["offset"] != resp["offset"]):
                break
        MAX_MTIME_MAP[cid] = this_max_mtime
        return count

    async def batch_load_videos():
        "加载若干个目录中的所有视频的 名字 和 pickcode 到缓存"
        nonlocal running_task, waiting_task, bcid
        if isinf(interval) and NAME_TO_PICKCODE:
            start = time()
            while time() < start + interval:
                waiting_task = create_task(sleep(interval))
                try:
                    await waiting_task
                except CancelledError as e:
                    if not e.args or e.args[0] == "shutdown":
                        return
                    cmd = e.args[0]
                    if cmd == "run":
                        break
                finally:
                    waiting_task = None
        while True:
            start = time()
            for bcid in iter_cids():
                this_start = time()
                running_task = create_task(load_videos(bcid))
                try:
                    count = await running_task
                    logger.info(f"successfully loaded cid={bcid}, {count} items, {time() - this_start:.6f} seconds")
                except CancelledError as e:
                    logger.warning(f"task cancelled cid={bcid}")
                    if not e.args or e.args[0] == "shutdown":
                        return
                    cmd = e.args[0]
                    if cmd == "sleep":
                        break
                except Exception:
                    logger.exception(f"error occurred while loading cid={bcid}")
                finally:
                    bcid = ""
                    running_task = None
            while time() < start + interval:
                waiting_task = create_task(sleep(interval))
                try:
                    await waiting_task
                except CancelledError as e:
                    if not e.args or e.args[0] == "shutdown":
                        return
                    cmd = e.args[0]
                    if cmd == "run":
                        break
                finally:
                    waiting_task = None

    async def queue_load_videos():
        nonlocal qrunning_task, qcid
        while True:
            qcid = await QUEUE.get()
            qrunning_task = create_task(load_videos(qcid))
            try:
                this_start = time()
                count = await qrunning_task
                logger.info(f"successfully loaded cid={qcid}, {count} items, {time() - this_start:.6f} seconds")
            except CancelledError as e:
                logger.warning(f"task cancelled cid={qcid}")
                if not e.args or e.args[0] == "shutdown":
                    return
            except:
                logger.exception(f"error occurred while loading cid={qcid}")
            finally:
                qcid = ""
                qrunning_task = None
                QUEUE.task_done()

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
            app="alipaymini", 
            check_for_relogin=True, 
        )
        async with client.async_session:
            app.services.register(P115Client, instance=client)
            yield

    @app.lifespan
    async def start_tasks(app: Application):
        batch_task = create_task(batch_load_videos())
        queue_task = create_task(queue_load_videos())
        try:
            yield
        finally:
            batch_task.cancel("shutdown")
            queue_task.cancel("shutdown")

    async def get_url(
        request: Request, 
        client: ClientSession, 
        p115client: P115Client, 
        name: str = "", 
        pickcode: str = "", 
        id: str = "", 
        sha1: str = "", 
        path: str = "", 
        sign: str = "", 
        t: int = 0, 
    ):
        def check_sign(value, /):
            if not token:
                return None
            if sign != calc_sha1(bytes(f"302@115-{token}-{t}-{value}", "utf-8")).hexdigest():
                return json({"state": False, "message": "invalid sign"}, 403)
            elif t > 0 and t <= time():
                return json({"state": False, "message": "url was expired"}, 401)
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
            if not (pickcode := ID_TO_PICKCODE.get(id, "")):
                resp = await p115client.fs_file_skim(id, async_=True, request=blacksheep_request, session=client)
                if resp and resp["state"]:
                    pickcode = ID_TO_PICKCODE[id] = resp["data"][0]["pick_code"]
        elif sha1 := sha1.strip().upper():
            if resp := check_sign(sha1):
                return resp
            if len(sha1) != 40 or sha1.strip(hexdigits):
                return json({"state": False, "message": f"bad sha1: {sha1!r}"}, 400)
            if not (pickcode := SHA1_TO_PICKCODE.get(sha1, "")):
                resp = await p115client.fs_shasearch(sha1, async_=True, request=blacksheep_request, session=client)
                if resp and resp["state"]:
                    pickcode = SHA1_TO_PICKCODE[sha1] = resp["data"]["pick_code"]
        elif path := unquote(path):
            if resp := check_sign(path):
                return resp
            try:
                id = str(await get_id_to_path(
                    p115client, 
                    path, 
                    async_=True, 
                    refresh=True, 
                    ensure_file=True, 
                    request=blacksheep_request, 
                    session=client, 
                ))
            except (FileNotFoundError, IsADirectoryError):
                return json({"state": False, "message": f"no such path: {path!r}"}, 404)
            else:
                if not (pickcode := ID_TO_PICKCODE.get(id, "")):
                    resp = await p115client.fs_file_skim(id, async_=True, request=blacksheep_request, session=client)
                    if resp and resp["state"]:
                        pickcode = resp["data"][0]["pick_code"]
        else:
            if not name:
                return json({"state": False, "message": "please provide a pickcode, id, sha1, path or name"}, 400)
            if resp := check_sign(name):
                return resp
            try:
                pickcode = NAME_TO_PICKCODE[name]
            except KeyError:
                return json({"state": False, "message": f"name not found: {name!r}"}, 404)
        user_agent = (request.get_first_header(b"User-agent") or b"").decode("latin-1")
        bytes_range = (request.get_first_header(b"Range") or b"").decode("latin-1")
        key: tuple = ()
        if bytes_range and not user_agent.lower().startswith(("vlc/", "oplayer/", "lavf/")):
            remote_addr = request.original_client_ip
            cooldown_key = (pickcode, remote_addr, user_agent, bytes_range)
            if cooldown_key in URL_COOLDOWN:
                return text("too many requests", 429)
            URL_COOLDOWN[cooldown_key] = None
            key = (pickcode, remote_addr, user_agent)
            if url := URL_CACHE.get(key):
                return redirect(url)
        try:
            url = await p115client.download_url(
                pickcode, 
                headers={"User-Agent": user_agent}, 
                request=blacksheep_request, 
                session=client, 
                async_=True, 
            )
        except P115OSError as e:
            return json(e.args[1], 500)
        except (FileNotFoundError, IsADirectoryError) as e:
            return json(e.args[1], 404)
        NAME_TO_PICKCODE[url["name"]] = ID_TO_PICKCODE[id] = SHA1_TO_PICKCODE[url["sha1"]] = url["pickcode"]
        if key:
            URL_CACHE[key] = url
        return redirect(url)

    @app.router.route("/", methods=["GET", "HEAD"])
    async def get_url_by_pickcode(
        request: Request, 
        client: ClientSession, 
        p115client: P115Client, 
        pickcode: str = "", 
        id: str = "", 
        sha1: str = "", 
        path: str = "", 
        sign: str = "", 
        t: int = 0, 
    ):
        """获取文件直链，用 pickcode 查询任意文件

        :param pickcode: 文件的提取码，优先级高于 `id`
        :param id: 文件的 id，优先级高于 `sha1`
        :param sha1: 文件的 sha1，优先级高于 `path`
        :param path: 文件的路径
        :param sign: 签名，计算方式为 `hashlib.sha1(bytes(f"302@115-{token}-{t}-{pickcode}", "utf-8")).hexdigest()`
            <br />- **token**&colon; 命令行中所传入的 token
            <br />- **t**&colon; 过期时间戳（超过这个时间后，链接不可用）
            <br />- **pickcode**&colon; 所传入的 `pickcode`
        :param t: 过期时间戳

        :return: 文件的直链
        """
        return await get_url(request, client, p115client, pickcode=pickcode, id=id, sha1=sha1, path=path)

    @app.router.route("/{path:name}", methods=["GET", "HEAD"])
    async def get_url_by_pickcode_or_name(
        request: Request, 
        client: ClientSession, 
        p115client: P115Client, 
        name: str = "", 
        pickcode: str = "", 
        id: str = "", 
        sha1: str = "", 
        path: str = "", 
        sign: str = "", 
        t: int = 0, 
    ):
        """获取文件直链，仅支持用文件名查询视频文件，或者用 pickcode 查询任意文件

        :param name: 文件名
        :param pickcode: 文件的提取码，优先级高于 `id`
        :param id: 文件的 id，优先级高于 `sha1`
        :param sha1: 文件的 sha1，优先级高于 `path`
        :param path: 文件的路径，优先级高于 `name`
        :param sign: 签名，计算方式为 `hashlib.sha1(bytes(f"302@115-{token}-{t}-{value}", "utf-8")).hexdigest()`
            <br />- **token**&colon; 命令行中所传入的 token
            <br />- **t**&colon; 过期时间戳（超过这个时间后，链接不可用）
            <br />- **value**&colon; 按顺序检查 `pickcode`、`name`，最先有效的那个值
        :param t: 过期时间戳

        :return: 文件的直链
        """
        return await get_url(request, client, p115client, name=name, pickcode=pickcode, id=id, sha1=sha1, path=path)

    @app.router.route("/run", methods=["POST"])
    async def do_run(request: Request, cid: str = "", password: str = ""):
        """运行后台任务

        :param cid: 如果不传 cid，则运行批量任务（正在运行则跳过，正在睡眠则运行一次）；如果传入 cid，则加入队列任务（只会被运行一次）
        :param password: 口令
        """
        if PASSWORD and PASSWORD != password:
            return json({"state": False, "message": "password does not match"}, 401)
        if cid:
            QUEUE.put_nowait(cid)
            return json({"state": True, "message": "ok"})
        try:
            waiting_task.cancel("run") # type: ignore
            return json({"state": True, "message": "ok"})
        except AttributeError:
            return json({"state": True, "message": "skip"})

    @app.router.route("/sleep", methods=["POST"])
    async def do_sleep(request: Request, password: str = ""):
        """终止运行批量开始，睡眠一定时间，如果正在睡眠则跳过

        :param password: 口令
        """
        if PASSWORD and PASSWORD != password:
            return json({"state": False, "message": "password does not match"}, 401)
        try:
            running_task.cancel("sleep") # type: ignore
            return json({"state": True, "message": "ok"})
        except AttributeError:
            return json({"state": True, "message": "skip"})

    @app.router.route("/skip", methods=["POST"])
    async def do_skip(request: Request, cid: str = "", password: str = ""):
        """跳过当前批量任务中正在运行的任务

        :param cid: 如果提供，则仅当正在运行的 cid 等于此 cid 时，才会取消任务
        :param password: 口令
        """
        if PASSWORD and PASSWORD != password:
            return json({"state": False, "message": "password does not match"}, 401)
        try:
            if not cid or cid == bcid:
                running_task.cancel("skip") # type: ignore
        except AttributeError:
            pass
        return json({"state": True, "message": "ok"})

    @app.router.route("/qskip", methods=["POST"])
    async def do_qskip(request: Request, cid: str = "", password: str = ""):
        """跳过当前队列任务中正在运行的任务

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
        if running_task is None:
            return json({"state": True, "message": "ok", "value": False})
        else:
            return json({"state": True, "message": "ok", "value": True, "cid": bcid})

    @app.router.route("/qrunning", methods=["POST"])
    async def get_queue_task_running(request: Request, password: str = ""):
        """队列任务中，是否有任务在运行中

        :param password: 口令
        """
        if PASSWORD and PASSWORD != password:
            return json({"state": False, "message": "password does not match"}, 401)
        if qrunning_task is None:
            return json({"state": True, "message": "ok", "value": False})
        else:
            return json({"state": True, "message": "ok", "value": True, "cid": qcid, "pending": list(getattr(QUEUE, "_queue"))})

    @app.router.route("/interval", methods=["POST"])
    async def set_interval(request: Request, value: float = nan, password: str = ""):
        """修改两次开始批量任务的最小时间间隔

        :param value: 如果不传入值，则获取原值，如果传入 inf，则永久睡眠
        :param password: 口令
        """
        nonlocal interval
        if PASSWORD and PASSWORD != password:
            return json({"state": False, "message": "password does not match"}, 401)
        if not isnan(value):
            interval = value
            try:
                waiting_task.cancel("change") # type: ignore
            except AttributeError:
                pass
            return json({"state": True, "message": "ok", "value": interval})
        return json({"state": True, "message": "skip", "value": interval})

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

    @app.router.route("/cids", methods=["POST"])
    async def get_cids(request: Request, password: str = ""):
        """获取 cid 列表，用于批量任务

        :param password: 口令
        """
        if PASSWORD and PASSWORD != password:
            return json({"state": False, "message": "password does not match"}, 401)
        return json({"state": True, "message": "ok", "value": list(CIDS)})

    @app.router.route("/cids/update", methods=["POST"])
    async def update_cids(request: Request, password: str = "", body: None | FromJSON[dict] = None):
        """添加 cid 列表，用于批量任务

        :param password: 口令
        :param body: 请求体为 json 格式 <code>{"value"&colon; ["cid1", "cid2", "..."]}</code>
        """
        if PASSWORD and PASSWORD != password:
            return json({"state": False, "message": "password does not match"}, 401)
        if body:
            payload = body.value
            cids_new = payload.get("value")
            if isinstance(cids_new, (int, str)):
                CIDS.add(str(cids_new))
                return json({"state": True, "message": "ok", "value": list(CIDS)})
            elif isinstance(cids_new, list):
                CIDS.update(map(str, cids_new))
                return json({"state": True, "message": "ok", "value": list(CIDS)})
        return json({"state": True, "message": "skip", "value": list(CIDS)})

    @app.router.route("/cids/discard", methods=["POST"])
    async def discard_cids(request: Request, password: str = "", body: None | FromJSON[dict] = None):
        """删除 cid 列表，用于批量任务

        :param password: 口令
        :param body: 请求体为 json 格式 <code>{"value"&colon; ["cid1", "cid2", "..."]}</code>
        """
        if PASSWORD and PASSWORD != password:
            return json({"state": False, "message": "password does not match"}, 401)
        if body:
            payload = body.value
            cids_new = payload.get("value")
            if isinstance(cids_new, (int, str)):
                CIDS.discard(str(cids_new))
                return json({"state": True, "message": "ok", "value": list(CIDS)})
            elif isinstance(cids_new, list):
                CIDS.difference_update(map(str, cids_new))
                return json({"state": True, "message": "ok", "value": list(CIDS)})
        return json({"state": True, "message": "skip", "value": list(CIDS)})

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
        cids=args.cids, 
        interval=args.interval, 
        store_file=args.store_file, 
        password=args.password or "", 
        token=args.token, 
        cookies_path=args.cookies_path, 
    )
    print(__doc__)
    uvicorn.run(
        app=app, 
        host=args.host, 
        port=args.port, 
        proxy_headers=True, 
        forwarded_allow_ips="*", 
    )

