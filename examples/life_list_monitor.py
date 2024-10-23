#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 2)
__all__ = ["main"]
__doc__ = "115 生活事件监控（周期轮询策略，最大延迟为 1 秒）"
__requirements__ = ["p115client", "urllib3", "urllib3_request"]

if __name__ == "__main__":
    from argparse import ArgumentParser, RawTextHelpFormatter

    parser = ArgumentParser(
        description=__doc__, 
        formatter_class=RawTextHelpFormatter, 
        epilog='''\t\t🔧🔨 使用技巧 🔩🪛

本工具可以自己提供 collect 函数的定义，因此具有一定的可定制性

1. 把日志输出到本地文件

.. code: python

    python life_list_monitor.py --collect '
    import logging
    from logging.handlers import TimedRotatingFileHandler

    logger = logging.getLogger("115 life")
    logger.setLevel(logging.INFO)
    handler = TimedRotatingFileHandler("115.log", when="midnight", backupCount=3650)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s"))
    logger.addHandler(handler)

    collect = logger.info
    '

2. 使用 mongodb 存储采集到的日志

.. code: python

    python life_list_monitor.py --collect '
    from pymongo import MongoClient

    client = MongoClient("localhost", 27017)
    collect = client.log["115"].insert_one
    '

3. 使用 sqlite 收集采集到的日志，单独开启一个线程作为工作线程

.. code: python

    python life_list_monitor.py --queue-collect --collect '
    from json import dumps
    from sqlite3 import connect
    from threading import local

    ctx = local()

    def collect(event):
        try:
            con = ctx.con
        except AttributeError:
            con = ctx.con = connect("115_log.db")
            con.execute("""
            CREATE TABLE IF NOT EXISTS log ( 
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
                data JSON 
            ); 
            """)
        try:
            con.execute("INSERT INTO log(data) VALUES (?)", (dumps(event),))
            con.commit()
        except:
            con.rollback()
            raise
    '

4. 如果并发量特别大，可以按批插入数据，以 mongodb 为例

第 1 种策略是收集到一定数量时，进行批量插入

.. code: python

    python life_list_monitor.py --collect '
    from atexit import register
    from threading import Lock

    from pymongo import MongoClient

    client = MongoClient("localhost", 27017)

    BATCHSIZE = 100

    cache = []
    push = cache.append
    insert_many = client.log["115"].insert_many
    cache_lock = Lock()

    def work():
        with cache_lock:
            if len(cache) >= BATCHSIZE:
                insert_many(cache)
                cache.clear()

    def collect(event):
        push(event)
        work()

    def end_work():
        with cache_lock:
            if cache:
                insert_many(cache)
                cache.clear()

    register(end_work)
    '

第 2 种策略是定期进行批量插入

.. code: python

    python life_list_monitor.py --collect '
    from atexit import register
    from time import sleep
    from _thread import start_new_thread

    from pymongo import MongoClient

    client = MongoClient("localhost", 27017)

    INTERVAL = 1
    running = True

    cache = []
    collect = cache.append
    insert_many = client.log["115"].insert_many

    def worker():
        while running:
            length = len(cache)
            if length:
                insert_many(cache[:length])
                del cache[:length]
            sleep(INTERVAL)

    def end_work():
        global running
        running = False
        if cache:
            cache_copy = cache.copy()
            cache.clear()
            insert_many(cache_copy)

    register(end_work)

    start_new_thread(worker, ())
    '
''')
    parser.add_argument("-c", "--cookies", help="115 登录 cookies，优先级高于 -cp/--cookies-path")
    parser.add_argument("-cp", "--cookies-path", help="存储 115 登录 cookies 的文本文件的路径")
    parser.add_argument("--collect", "--collect", default="", help="""\
提供一段代码，里面必须暴露一个名为 collect 的函数，这个函数接受一个位置参数，用来传入 1 条日志
除此以外，我还会给这个函数注入一些全局变量
    - logger: 日志对象

默认的行为是把信息输出到日志里面，代码为

    collect = logger.info

""")
    parser.add_argument("-qc", "--queue-collect", action="store_true", 
                    help=f"单独启动个线程用来执行收集，通过队列进行中转")
    parser.add_argument("-v", "--version", action="store_true", help="输出版本号")

    args = parser.parse_args()
    if args.version:
        print(".".join(map(str, __version__)))
        raise SystemExit(0)

try:
    from p115client import P115Client
    from urllib3 import PoolManager
    from urllib3_request import request
except ImportError:
    from sys import executable
    from subprocess import run
    run([executable, "-m", "pip", "install", "-U", *__requirements__], check=True)
    from p115client import P115Client
    from urllib3 import PoolManager
    from urllib3_request import request

import logging

from collections.abc import Callable
from datetime import datetime
from functools import partial
from itertools import count
from pathlib import Path
from _thread import start_new_thread
from time import sleep, time
from typing import Any


logger = logging.getLogger("lift_list_monitor")
handler = logging.StreamHandler()
logger.setLevel(logging.INFO)
formatter = logging.Formatter(
    "[\x1b[1m%(asctime)s\x1b[0m] (\x1b[1;32m%(levelname)s\x1b[0m) \x1b[5;31m➜\x1b[0m %(message)s"
)
handler.setFormatter(formatter)
logger.addHandler(handler)

#+ 新增
#+ 文件重命名
#+ 复制文件


def iter_files(client, cid, first_page_size=0, page_size=10_000):
    if page_size <= 0:
        page_size = 10_000
    if first_page_size <= 0:
        first_page_size = page_size
    payload = {"asc": 0, "cid": cid, "cur": 0, "limit": first_page_size, "offset": 0, "o": "user_utime", "show_dir": 0}
    for i in count(0):
        resp = client.fs_files_app(payload)
        if cid and int(resp["path"][-1]["cid"]) != cid:
            break
        if resp["offset"] != payload["offset"]:
            break
        if i == 0:
            payload["limit"] = page_size
        yield from map(normalize_attr, resp["data"])
        payload["offset"] += len(resp["data"]) # type: ignore
        if payload["offset"] >= resp["count"]:
            break


def normalize_attr(info, /) -> dict:
    """翻译 `P115Client.fs_files`、`P115Client.fs_search`、`P115Client.share_snap` 等接口响应的文件信息数据，使之便于阅读

    :param info: 原始数据
    :param keep_raw: 是否保留原始数据，如果为 True，则保存到 "raw" 字段

    :return: 翻译后的 dict 类型数据
    """
    attr = {}
    attr["user_id"] = info["fuuid"]
    attr["file_id"] = info["fid"]
    attr["parent_id"] = info["pid"]
    attr["file_name"] = info["fn"]
    attr["file_category"] = int(info["fc"])
    attr["file_type"] = int(info.get("ftype") or 0)
    attr["file_size"] = int(info.get("fs") or 0)
    attr["sha1"] = info.get("sha1", "")
    attr["pick_code"] = info["pc"]
    attr["fl"] = info["fl"]
    attr["ico"] = info.get("ico", "")
    if "thumb" in info:
        attr["thumb"] = f"https://imgjump.115.com?{info['thumb']}&size=0&sha1={info['sha1']}"
    attr["create_time"] = int(info["uppt"])
    attr["update_time"] = int(info["upt"])
    for key, name in (
        ("ism", "is_mark"), 
        ("is_top", "is_top"), 
        ("isp", "is_private"), 
        ("ispl", "show_play_long"), 
        ("iss", "is_share"), 
        ("isv", "isv"), 
        ("issct", "is_shortcut"), 
        ("ic", "violated"), 
    ):
        if key in info:
            attr[name] = int(info[key] or 0)
    for key, name in (
        ("def", "def"), 
        ("def2", "def2"), 
        ("fco", "cover"), 
        ("fdesc", "desc"), 
        ("flabel", "fflabel"), 
        ("multitrack", "multitrack"), 
        ("play_long", "play_long"), 
        ("d_img", "d_img"), 
        ("v_img", "v_img"), 
        ("audio_play_long", "audio_play_long"), 
        ("current_time", "current_time"), 
        ("last_time", "last_time"), 
        ("played_end", "played_end"), 
    ):
        if key in info:
            attr[name] = info[key]
    return attr


def main(
    cookies: str | Path = Path(__file__).parent / "115-cookies.txt", 
    collect: None | Callable[[dict], Any] = logger.info, 
    queue_collect: bool = False, 
):
    if collect is None:
        collect = logger.info
    client = P115Client(cookies, app="harmony", ensure_cookies=True, check_for_relogin=True)
    urlopen = partial(request, pool=PoolManager(num_pools=50))
    client.life_calendar_setoption(request=urlopen)
    log_error = logger.exception
    running = True
        
    # NOTE: 文件信息缓存（不包括目录）
    file_id_to_name: dict[int, str] = {}
    file_id_to_mtime: dict[int, int] = {}

    def watch(cid):
        # TODO: 使用增量比较增略
        # start = int(time())
        for attr in iter_files(client, cid):
            file_id = attr["file_id"]
            file_id_to_name[file_id] = attr["file_name"]
            file_id_to_mtime[file_id] = attr["update_time"]
        while running:
            for attr in iter_files(client, cid, 1000):
                # if attr["update_time"] < start:
                #     break
                file_id = attr["file_id"]
                if name := file_id_to_name.get(file_id):
                    if name != attr["file_name"]:
                        file_id_to_name[file_id] = attr["file_name"]
                        file_id_to_mtime[file_id] = attr["update_time"]
                        attr["type"] = 99
                        attr["behavior_type"] = "rename_file"
                        collect(attr) # type: ignore
                else:
                    file_id_to_name[file_id] = attr["file_name"]
                    file_id_to_mtime[file_id] = attr["update_time"]
                    attr["type"] = 99
                    attr["behavior_type"] = "add_file"
                    collect(attr) # type: ignore
            start = int(time())
    cid = 2580587204111760961
    start_new_thread(watch, (cid,))

    if queue_collect:
        from queue import Queue

        queue: Queue = Queue()
        work = collect
        collect = queue.put
        get_task = queue.get
        task_done = queue.task_done

        def worker():
            while running:
                task = get_task()
                try:
                    work(task)
                except BaseException as e:
                    log_error(e)
                finally:
                    task_done()

        start_new_thread(worker, ())

    collection_start_time = str(datetime.now())
    get_id = count(1).__next__
    end_time = int(time())
    start_time = end_time - 2
    try:
        while True:
            try:
                resp = client.life_list(
                    {"show_type": 0, "start_time": start_time, "end_time": end_time}, 
                    request=urlopen, 
                )
            except Exception as e:
                log_error(e)
                continue
            data = resp["data"]
            if data["count"]:
                for items in data["list"]:
                    if "items" not in items:
                        if start_time < items["update_time"] < end_time:
                            items["update_time_str"] = str(datetime.fromtimestamp(items["update_time"]))
                            items["collection_start_time"] = collection_start_time
                            items["collection_id"] = get_id()
                            collect(items)
                        continue
                    behavior_type = items["behavior_type"]
                    date = items["date"]
                    for item in items["items"]:
                        item["behavior_type"] = behavior_type
                        item["date"] = date
                        item["update_time_str"] = str(datetime.fromtimestamp(item["update_time"]))
                        item["collection_start_time"] = collection_start_time
                        item["collection_id"] = get_id()
                        file_id = item["file_id"]
                        if behavior_type in ("upload_file", "upload_image_file", "move_file", "move_image_file"):
                            if item.get("file_category"):
                                file_id_to_name[file_id] = item["file_name"]
                                file_id_to_mtime[file_id] = int(item["update_time"])
                        elif behavior_type == "delete_file":
                            file_id_to_name.pop(file_id, None)
                            file_id_to_mtime.pop(file_id, None)
                        collect(item)
                    if behavior_type.startswith("upload_") or len(items["items"]) == 10 and items["total"] > 10:
                        seen_items: set[str] = {item["id"] for item in items["items"]}
                        payload = {"offset": 0, "limit": 32, "type": behavior_type, "date": date}
                        while True:
                            try:
                                resp = client.life_behavior_detail(payload, request=urlopen)
                            except Exception as e:
                                log_error(e)
                                continue
                            for item in resp["data"]["list"]:
                                if item["id"] in seen_items or item["update_time"] >= end_time:
                                    continue
                                elif item["update_time"] <= start_time:
                                    break
                                seen_items.add(item["id"])
                                item["behavior_type"] = behavior_type
                                item["date"] = date
                                item["update_time_str"] = str(datetime.fromtimestamp(item["update_time"]))
                                item["collection_start_time"] = collection_start_time
                                item["collection_id"] = get_id()
                                if item.get("file_category"):
                                    file_id = item["file_id"]
                                    file_id_to_name[file_id] = item["file_name"]
                                    file_id_to_mtime[file_id] = int(item["update_time"])
                                collect(item)
                            else:
                                if not resp["data"]["next_page"]:
                                    break
                                payload["offset"] += 32
                                continue
                            break
                start_time = data["list"][0]["update_time"]
            if (diff := time() - end_time) < 1:
                sleep(1-diff)
            end_time = int(time())
    finally:
        running = False


if __name__ == "__main__":
    from textwrap import dedent

    if cookies := args.cookies:
        pass
    elif cookies_path := args.cookies_path:
        cookies = Path(cookies_path)
    elif not cookies:
        cookies = Path("~/115-cookies.txt").expanduser()
    collect = None
    if code := dedent(args.collect).strip():
        ns: dict = {"logger": logger}
        exec(code, ns)
        collect = ns["collect"]
    main(
        cookies=cookies, 
        collect=collect, 
        queue_collect=args.queue_collect, 
    )

# TODO: 以后会直接从 websocket 获取数据，或者更短的轮询时间，提供实时性
# TODO: 支持只监控特定的事件列表
# TODO: 更详细的文档，以说明所能监控的事件范围
# TODO: 支持一定时间返回的回溯，以监测一些删除事件，如果这个事件之前看到，现在看不到，说明文件被还原
# TODO: 支持不休眠轮询，甚至并发轮询，每隔 0.1 秒发送一个查询，以增强实时性
# TODO: 找到新的接口，以规避风控
