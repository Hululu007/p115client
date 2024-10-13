#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 2)
__all__ = ["main"]
__doc__ = "115 生活事件监控（周期轮询策略，最大延迟为 1 秒）"
__requirements__ = ["p115client", "urllib3", "urllib3_request"]

# TODO: 以后会直接从 websocket 获取数据，提供实时性

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


def main(
    cookies: None | str | Path = Path(__file__).parent / "115-cookies.txt", 
    collect: None | Callable[[dict], Any] = logger.info, 
    queue_collect: bool = False, 
):
    if not cookies:
        cookies = Path(__file__).parent / "115-cookies.txt"
    if collect is None:
        collect = logger.info
    client = P115Client(cookies, app="harmony", check_for_relogin=True)
    urlopen = partial(request, pool=PoolManager(num_pools=50))
    client.life_calendar_setoption(request=urlopen)
    log_error = logger.exception
    running = True

    if queue_collect:
        from _thread import start_new_thread
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
                        collect(item)
                    if behavior_type == "upload_file" or len(items["items"]) == 10 and items["total"] > 10:
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

    if not (cookies := args.cookies) and (cookies_path := args.cookies_path):
        cookies = Path(cookies_path)
    if not cookies:
        cookies = None
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

