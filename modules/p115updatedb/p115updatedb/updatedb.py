#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = ["updatedb_life", "updatedb_one", "updatedb_tree", "updatedb"]

import logging

from collections import deque
from collections.abc import Collection, Iterator, Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from errno import EBUSY
from itertools import cycle, takewhile
from math import inf, isnan, isinf
from posixpath import splitext
from sqlite3 import connect, Connection, Cursor
from string import digits
from time import perf_counter
from typing import cast, Final, NoReturn

from concurrenttools import run_as_thread
from orjson import dumps
from p115client import check_response, P115Client
from p115client.const import CLASS_TO_TYPE, SUFFIX_TO_TYPE
from p115client.exception import BusyOSError, DataError
from p115client.tool.edit import update_desc, update_star
from p115client.tool.iterdir import filter_na_ids, get_id_to_path, iter_stared_dirs
from p115client.tool.life import iter_life_behavior, IGNORE_BEHAVIOR_TYPES
from sqlitetools import execute, find, query, transact, upsert_items, AutoCloseConnection

from .query import (
    get_parent_id, has_id, iter_descendants_fast, iter_existing_id, 
    iter_parent_id, select_mtime_groups, 
)
from .util import ZERO_DICT, bfs_gen


# NOTE: 需要 mtime 的 115 生活事件类型集
MTIME_BEHAVIOR_TYPES: Final = frozenset((1, 2, 14, 17, 18, 20))
# NOTE: 需要 ctime 的 115 生活事件类型集
CTIME_BEHAVIOR_TYPES: Final = frozenset((1, 2, 14, 17, 18))
# NOTE: 初始化日志对象
logger = logging.Logger("115-updatedb", level=logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    "[\x1b[1m%(asctime)s\x1b[0m] (\x1b[1;36m%(levelname)s\x1b[0m) "
    "\x1b[0m\x1b[1;35m%(name)s\x1b[0m \x1b[5;31m➜\x1b[0m %(message)s"
))
logger.addHandler(handler)
# NOTE: 轮流获取 proapi 的 origin
get_proapi = cycle(("http://proapi.115.com", "http://pro.api.115.com")).__next__


def initdb(con: Connection | Cursor, /, disable_event: bool = False) -> Cursor:
    """初始化数据库，会尝试创建一些表、索引、触发器等，并把表的 "journal_mode" 改为 WAL (write-ahead-log)

    :param con: 数据库连接或游标

    :return: 游标
    """
    sql = """\
-- 修改日志模式为 WAL (write-ahead-log)
PRAGMA journal_mode = WAL;

-- data 表
CREATE TABLE IF NOT EXISTS data (
    id INTEGER NOT NULL PRIMARY KEY,   -- 文件或目录的 id
    parent_id INTEGER NOT NULL,        -- 上级目录的 id
    pickcode TEXT NOT NULL DEFAULT '', -- 提取码，下载时需要用到
    sha1 TEXT NOT NULL DEFAULT '',     -- 文件的 sha1 散列值
    name TEXT NOT NULL,                -- 名字
    size INTEGER NOT NULL DEFAULT 0,   -- 文件大小
    is_dir INTEGER NOT NULL CHECK(is_dir IN (0, 1)), -- 是否目录
    type INTEGER NOT NULL DEFAULT 0,   -- 文件类型，目录的 type 总是 0
    ctime INTEGER NOT NULL DEFAULT 0,  -- 创建时间戳，一旦设置就不会更新
    mtime INTEGER NOT NULL DEFAULT 0,  -- 更新时间戳，如果名字、备注被设置（即使值没变），或者（如果自己是目录）进出回收站或增删直接子节点或设置封面，会更新此值，但移动并不更新
    is_collect INTEGER NOT NULL DEFAULT 0 CHECK(is_collect IN (0, 1)), -- 是否已被标记为违规
    is_alive INTEGER NOT NULL DEFAULT 1 CHECK(is_alive IN (0, 1)),   -- 是否存在中（未被移除）
    updated_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+08:00', 'now', '+8 hours')) -- 最近一次更新时间
);

-- dir 表，用来存储所有看到的目录数据
CREATE TABLE IF NOT EXISTS dir (
    id INTEGER NOT NULL PRIMARY KEY,   -- 目录的 id
    parent_id INTEGER NOT NULL,        -- 上级目录的 id
    name TEXT NOT NULL,                -- 名字
    mtime INTEGER NOT NULL DEFAULT 0   -- 更新时间戳，如果名字、备注被设置（即使值没变），或者进出回收站，或者增删直接子节点，或者设置封面，会更新此值，但移动并不更新
);

-- 创建 life 表，用来收集 115 生活事件
CREATE TABLE IF NOT EXISTS life (
    id INTEGER NOT NULL PRIMARY KEY, -- 事件 id
    data JSON NOT NULL,              -- 事件日志数据
    create_time INTEGER NOT NULL     -- 事件时间
);

-- 创建 event 表，用于记录 data 表上发生的变更事件
CREATE TABLE IF NOT EXISTS event (
    _id INTEGER PRIMARY KEY AUTOINCREMENT, -- 主键
    id INTEGER NOT NULL,   -- 文件或目录的 id
    old JSON DEFAULT NULL, -- 更新前的值
    diff JSON NOT NULL,    -- 将更新的值
    fs JSON NOT NULL,      -- 发生的文件系统事件列表：add:新增，remove:移除，revert:还原，move:移动，rename:重名
    created_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+08:00', 'now', '+8 hours')) -- 创建时间
);

-- 触发器
CREATE TRIGGER IF NOT EXISTS trg_data_before_update
BEFORE UPDATE ON data
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN NEW.mtime < OLD.mtime THEN RAISE(IGNORE)
    END;
END;

-- 索引
CREATE INDEX IF NOT EXISTS idx_data_pid ON data(parent_id);
CREATE INDEX IF NOT EXISTS idx_data_pc ON data(pickcode);
CREATE INDEX IF NOT EXISTS idx_data_sha1 ON data(sha1);
CREATE INDEX IF NOT EXISTS idx_data_name ON data(name);
CREATE INDEX IF NOT EXISTS idx_data_utime ON data(updated_at);
CREATE INDEX IF NOT EXISTS idx_dir_mtime ON dir(mtime);
CREATE INDEX IF NOT EXISTS idx_life_create ON life(create_time);
CREATE INDEX IF NOT EXISTS idx_event_create ON event(created_at);
"""
    if disable_event:
        sql += """
DROP TRIGGER IF EXISTS trg_data_insert;
CREATE TRIGGER trg_data_insert
AFTER INSERT ON data
FOR EACH ROW
BEGIN
    SELECT NULL;
END;

DROP TRIGGER IF EXISTS trg_data_update;
CREATE TRIGGER trg_data_update
AFTER UPDATE ON data 
FOR EACH ROW
BEGIN
    UPDATE data SET updated_at = strftime('%Y-%m-%dT%H:%M:%f+08:00', 'now', '+8 hours') WHERE id = NEW.id;
END;"""
    else:
        sql += """
-- 触发器，记录 data 表 'insert'
DROP TRIGGER IF EXISTS trg_data_insert;
CREATE TRIGGER trg_data_insert
AFTER INSERT ON data
FOR EACH ROW
BEGIN
    INSERT INTO event(id, diff, fs) VALUES (
        new.id, 
        json_object(
            'id', new.id, 
            'parent_id', new.parent_id, 
            'pickcode', new.pickcode, 
            'sha1', new.sha1, 
            'name', new.name, 
            'size', new.size, 
            'is_dir', new.is_dir, 
            'type', new.type, 
            'ctime', new.ctime, 
            'mtime', new.mtime, 
            'is_collect', new.is_collect, 
            'is_alive', new.is_alive
        ), 
        JSON_ARRAY('add')
    );
END;

-- 触发器，记录 data 表 'update'
DROP TRIGGER IF EXISTS trg_data_update;
CREATE TRIGGER trg_data_update
AFTER UPDATE ON data 
FOR EACH ROW
BEGIN
    UPDATE data SET updated_at = strftime('%Y-%m-%dT%H:%M:%f+08:00', 'now', '+8 hours') WHERE id = NEW.id;
    INSERT INTO event(id, old, diff, fs)
    SELECT *, (
        WITH t(event) AS (
            VALUES 
                (CASE WHEN diff->>'is_alive' THEN 'revert' END), 
                (CASE WHEN diff->>'is_alive' = 0 THEN 'remove' END), 
                (CASE WHEN diff->>'name' IS NOT NULL THEN 'rename' END), 
                (CASE WHEN diff->>'parent_id' IS NOT NULL THEN 'move' END)
        )
        SELECT JSON_GROUP_ARRAY(event) FROM t WHERE event IS NOT NULL
    )
    FROM (
        WITH data(id, old, new) AS (
            SELECT
                NEW.id, 
                JSON_OBJECT(
                    'id', OLD.id, 
                    'parent_id', OLD.parent_id, 
                    'pickcode', OLD.pickcode, 
                    'sha1', OLD.sha1, 
                    'name', OLD.name, 
                    'size', OLD.size, 
                    'is_dir', OLD.is_dir, 
                    'type', OLD.type, 
                    'ctime', OLD.ctime, 
                    'mtime', OLD.mtime, 
                    'is_collect', OLD.is_collect, 
                    'is_alive', OLD.is_alive
                ) AS old, 
                JSON_OBJECT(
                    'id', NEW.id, 
                    'parent_id', NEW.parent_id, 
                    'pickcode', NEW.pickcode, 
                    'sha1', NEW.sha1, 
                    'name', NEW.name, 
                    'size', NEW.size, 
                    'is_dir', NEW.is_dir, 
                    'type', NEW.type, 
                    'ctime', NEW.ctime, 
                    'mtime', NEW.mtime, 
                    'is_collect', NEW.is_collect, 
                    'is_alive', NEW.is_alive
                ) AS new
        ), old(key, value) AS (
            SELECT tbl.key, tbl.value FROM data, JSON_EACH(data.old) AS tbl
        ), new(key, value) AS (
            SELECT tbl.key, tbl.value FROM data, JSON_EACH(data.new) AS tbl
        ), diff(diff) AS (
            SELECT JSON_GROUP_OBJECT(key, new.value)
            FROM old JOIN new USING (key)
            WHERE old.value != new.value
        )
        SELECT data.id, data.old, diff.diff FROM data, diff WHERE data.old != data.new
    );
END;"""
    return con.executescript(sql)


def insert_dir_items(con, items, commit: bool = False):
    upsert_items(
        con, 
        items, 
        table="dir", 
        fields=("id", "parent_id", "name", "mtime"), 
        commit=commit, 
    )


def kill_items(
    con: Connection | Cursor, 
    ids: int | Iterable[int], 
    /, 
    commit: bool = False, 
) -> Cursor:
    """使用 id 去筛选和移除一组数据

    :param con: 数据库连接或游标
    :param ids: 一组 id，会被移除
    :param commit: 是否提交

    :return: 游标
    """
    if isinstance(ids, int):
        cond = f"id = {ids:d}"
    else:
        cond = "id IN (%s)" % (",".join(map(str, ids)) or "NULL")
    sql = "UPDATE data SET is_alive=0 WHERE " + cond
    return execute(con, sql, commit=commit)


def update_stared_dirs(
    con: Connection | Cursor, 
    /, 
    client: P115Client, 
    **request_kwargs, 
) -> list[dict]:
    """从网上增量拉取目录数据，并更新到数据库

    :param con: 数据库连接或游标
    :param client: 115 网盘客户端对象
    :param request_kwargs: 其它 http 请求参数，会传给具体的请求函数，默认的是 httpx，可用参数 request 进行设置

    :return: 拉取下来的新增或更新的目录的信息字典列表
    """
    mtime = find(con, "SELECT COALESCE(MAX(mtime), 0) FROM dir")
    data: list[dict] = list(takewhile(
        lambda attr: attr["mtime"] > mtime or has_id(con, attr["id"]), 
        iter_stared_dirs(
            client, 
            order="user_utime", 
            asc=0, 
            first_page_size=64, 
            id_to_dirnode=ZERO_DICT, 
            normalize_attr=normalize_attr, 
            app="android", 
            **request_kwargs, 
        ), 
    ))
    if data:
        with transact(con) as cur:
            insert_dir_items(cur, data)
            upsert_items(cur, data)
    return data


def is_timeouterror(exc: Exception) -> bool:
    exctype = type(exc)
    for exctype in exctype.mro():
        if exctype is Exception:
            break
        if "Timeout" in exctype.__name__:
            return True
    return False


def iterdir(
    client: P115Client, 
    cid: int = 0, 
    /, 
    first_page_size: int = 0, 
    page_size: int = 10_000, 
    payload: dict = {}, 
    **request_kwargs, 
) -> tuple[int, list[dict], set[int], Iterator[dict]]:
    """拉取一个目录中的文件或目录的数据

    :param client: 115 网盘客户端对象
    :param cid: 目录的 id
    :param first_page_size: 首次拉取的分页大小，如果为 None 或者 <= 0，自动确定
    :param page_size: 分页大小
    :param payload: 其它查询参数
    :param request_kwargs: 其它 http 请求参数，会传给具体的请求函数，默认的是 httpx，可用参数 request 进行设置

    :return: 4 元组，分别是

        1. 总数
        2. 祖先节点的简略信息（不含根目录）
        3. 已经拉取的文件或目录的 id 的集合
        4. 迭代器，用来获取数据
    """
    if page_size <= 0:
        page_size = 10_000
    if first_page_size <= 0:
        first_page_size = page_size
    payload = {
        "asc": 0, "cid": cid, "custom_order": 1, "fc_mix": 1, "o": "user_utime", "offset": 0, 
        "limit": first_page_size, "show_dir": 1, **payload, 
    }
    fs_files = client.fs_files_app
    def get_files(payload, /):
        while True:
            try:
                request_kwargs["base_url"] = get_proapi()
                return check_response(fs_files(payload, **request_kwargs))
            except DataError:
                if payload["limit"] <= 1150:
                    raise
                payload["limit"] -= 1_000
                if payload["limit"] < 1150:
                    payload["limit"] = 1150
    resp = get_files(payload)
    if cid and int(resp["path"][-1]["cid"]) != cid:
        raise NotADirectoryError(cid)
    count = resp["count"]
    ancestors = [
        {"id": a["cid"], "parent_id": a["pid"], "name": a["name"]} 
        for a in resp["path"][1:]
    ]
    seen: set[int] = set()
    seen_add = seen.add
    payload["limit"] = page_size
    def iterate():
        nonlocal resp
        offset = int(payload["offset"])
        payload["limit"] = page_size
        dirs: deque[dict] = deque()
        push, pop = dirs.append, dirs.popleft
        while True:
            data = resp["data"]
            for attr in map(normalize_attr, data):
                fid = cast(int, attr["id"])
                if fid in seen:
                    raise BusyOSError(
                        EBUSY, 
                        f"duplicate id found, means that some unpulled items have been updated: cid={cid}", 
                    )
                seen_add(fid)
                if attr["is_dir"]:
                    push(attr)
                else:
                    if dirs:
                        mtime = attr["mtime"]
                        while dirs and dirs[0]["mtime"] >= mtime:
                            yield pop()
                    yield attr
            offset += len(data)
            if offset >= count:
                yield from dirs
                break
            payload["offset"] = offset
            resp = get_files(payload)
            if cid and int(resp["path"][-1]["cid"]) != cid:
                raise FileNotFoundError(cid)
            ancestors[:] = (
                {"id": a["cid"], "parent_id": a["pid"], "name": a["name"]} 
                for a in resp["path"][1:]
            )
            if count != resp["count"]:
                raise BusyOSError(f"count changes during iteration: {cid}")
    return count, ancestors, seen, iterate()


def diff_dir(
    con: Connection | Cursor, 
    client: P115Client, 
    id: int = 0, 
    /, 
    tree: bool = False, 
    **request_kwargs, 
) -> tuple[list[dict], list[int]]:
    """拉取数据，确定哪些记录需要移除或更替

    :param con: 数据库连接或游标
    :param client: 115 网盘客户端对象
    :param id: 目录的 id
    :param tree: 如果为 True，则比对目录树，但仅对文件，即叶子节点，如果为 False，则比对所有直接（1 级）子节点，包括文件和目录
    :param request_kwargs: 其它 http 请求参数，会传给具体的请求函数，默认的是 httpx，可用参数 request 进行设置

    :return: 2 元组，1) 待更替的数据列表，2) 待移除的 id 列表
    """
    future = run_as_thread(select_mtime_groups, con, id, tree=tree)
    if tree:
        count, ancestors, seen, data_it = iterdir(client, id, first_page_size=128, payload={"show_dir": 0}, **request_kwargs)
    else:
        count, ancestors, seen, data_it = iterdir(client, id, first_page_size=16, **request_kwargs)
    remains, groups = future.result()
    dirs: list[dict] = []
    upsert_list: list[dict] = []
    remove_list: list[int] = []
    dirs_add = dirs.append
    upsert_add = upsert_list.append
    remove_extend = remove_list.extend
    result = upsert_list, remove_list
    try:
        if remains:
            his_it = iter(groups)
            his_mtime, his_ids = next(his_it)
        for n, attr in enumerate(data_it, 1):
            if attr["is_dir"]:
                dirs_add(attr)
            if remains:
                cur_id = attr["id"]
                cur_mtime = attr["mtime"]
                try:
                    while his_mtime > cur_mtime:
                        remove_extend(his_ids - seen)
                        remains -= len(his_ids)
                        his_mtime, his_ids = next(his_it)
                except StopIteration:
                    continue
                if his_mtime == cur_mtime and cur_id in his_ids:
                    remains -= 1
                    if n + remains == count:
                        return result
                    his_ids.remove(cur_id)
                    continue
            upsert_add(attr)
        if remains:
            remove_extend(his_ids - seen)
            for _, his_ids in his_it:
                remove_extend(his_ids - seen)
        return result
    finally:
        with transact(con) as cur:
            if ancestors:
                upsert_items(cur, ancestors, extras={"is_alive": 1, "is_dir": 1})
                upsert_items(cur, ancestors, table="dir")
            if dirs:
                upsert_items(cur, dirs, extras={"is_alive": 1})
                insert_dir_items(cur, dirs)


def normalize_attr(info: Mapping, /) -> dict:
    """筛选和规范化数据的名字，以便插入 `data` 表

    :param info: 原始数据

    :return: 经过规范化后的数据
    """
    def typeof(attr):
        if attr["is_dir"]:
            return 0
        if int(info.get("iv", info.get("isv", 0))):
            return 4
        if "muc" in info:
            return 3
        if fclass := info.get("class", ""):
            if type := CLASS_TO_TYPE.get(fclass):
                return type
            else:
                return 99
        if type := SUFFIX_TO_TYPE.get(splitext(attr["name"])[1].lower()):
            return type
        elif "play_long" in info:
            return 4
        return 99
    if "fn" in info:
        is_dir = info["fc"] == "0"
        attr = {
            "id": int(info["fid"]), 
            "parent_id": int(info["pid"]), 
            "pickcode": info["pc"], 
            "sha1": info.get("sha1") or "", 
            "name": info["fn"], 
            "size": int(info.get("fs") or 0), 
            "is_dir": is_dir, 
            "ctime": int(info["uppt"]), 
            "mtime": int(info["upt"]), 
            "is_collect": int(info.get("ic") or 0) == 1, 
            "is_alive": 1, 
        }
    else:
        is_dir = "fid" not in info
        attr = {
            "id": int(info["cid" if is_dir else "fid"]), 
            "parent_id": int(info["pid" if is_dir else "cid"]), 
            "pickcode": info["pc"], 
            "sha1": info.get("sha") or "", 
            "name": info["n"], 
            "size": int(info.get("s") or 0), 
            "is_dir": is_dir, 
            "ctime": int(info.get("tp") or 0), 
            "mtime": int(info.get("te") or 0), 
            "is_collect": int(info.get("c") or 0) == 1, 
            "is_alive": 1, 
        }
    attr["type"] = typeof(attr)
    return attr


def _init_client(
    client: str | P115Client, 
    dbfile: None | str | Connection | Cursor = None, 
    disable_event: bool = False, 
) -> tuple[P115Client, Connection | Cursor]:
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if not dbfile:
        dbfile = f"115-{client.user_id}.db"
    if isinstance(dbfile, (Connection, Cursor)):
        con = dbfile
    else:
        con = connect(
            dbfile, 
            uri=dbfile.startswith("file:"), 
            check_same_thread=False, 
            factory=AutoCloseConnection, 
            timeout=inf, 
        )
        initdb(con, disable_event=disable_event)
    return client, con


def updatedb_life(
    client: str | P115Client, 
    dbfile: None | str | Connection | Cursor = None, 
    from_time: int | float = 0, 
    from_id: int = 0, 
    interval: int | float = 0, 
    **request_kwargs, 
) -> NoReturn:
    """持续采集 115 生活日志，以更新数据库

    :param client: 115 网盘客户端对象
    :param dbfile: 数据库文件路径，如果为 None，则自动确定
    :param from_time: 开始时间（含），若为 0 则从当前时间开始，若小于 0 则从最早开始
    :param from_id: 开始的事件 id （不含）
    :param interval: 睡眠时间间隔，如果小于等于 0，则不睡眠
    :param request_kwargs: 其它 http 请求参数，会传给具体的请求函数，默认的是 httpx，可用参数 request 进行设置
    """
    client, con = _init_client(client, dbfile)
    for event in iter_life_behavior(
        client, 
        from_time=from_time, 
        from_id=from_id, 
        interval=interval, 
        ignore_types=(), 
        app="android", 
    ):
        type = event["type"]
        create_time = int(event["create_time"])
        if type not in IGNORE_BEHAVIOR_TYPES:
            sha1 = event["sha1"]
            is_dir = not sha1
            id = int(event["file_id"])
            parent_id = int(event["parent_id"])
            attr = {
                "id": id, 
                "parent_id": parent_id, 
                "pickcode": event["pick_code"], 
                "sha1": sha1, 
                "name": event["file_name"], 
                "size": int(event.get("file_size") or 0), 
                "is_dir": is_dir, 
                "is_alive": 1, 
            }
            if type == 22:
                attr["is_alive"] = 0
            if type in MTIME_BEHAVIOR_TYPES:
                attr["mtime"] = create_time
            if type in CTIME_BEHAVIOR_TYPES:
                attr["ctime"] = create_time
            if is_dir:
                attr["type"] = 0
            elif event.get("is_v"):
                attr["type"] = 4
            elif "muc" in event:
                attr["type"] = 3
            elif event.get("thumb", "").startswith("?"):
                attr["type"] = 2
            else:
                attr["type"] = SUFFIX_TO_TYPE.get(splitext(attr["name"])[-1].lower(), 99)
            if not has_id(con, parent_id):
                ancestors: list[dict] = []
                try:
                    if parent_id == 0:
                        pass
                    elif is_dir:
                        request_kwargs["base_url"] = get_proapi()
                        resp = check_response(client.fs_files_app({"cid": id, "hide_data": 1}, **request_kwargs))
                        if int(resp["path"][-1]["cid"]) == id:
                            ancestors.extend(
                                {"id": int(a["cid"]), "parent_id": int(a["pid"]), "name": a["name"]} 
                                for a in resp["path"][1:]
                            )
                    else:
                        request_kwargs["base_url"] = get_proapi()
                        resp = check_response(client.fs_category_get_app(id, **request_kwargs))
                        pid = 0
                        for a in resp["paths"][1:]:
                            fid = int(a["file_id"])
                            ancestors.append({"id": fid, "parent_id": pid, "name": a["file_name"]})
                            pid = fid
                except FileNotFoundError:
                    pass
                if ancestors:
                    with transact(con) as cur:
                        upsert_items(cur, ancestors, extras={"is_alive": 1, "is_dir": 1})
                        upsert_items(cur, ancestors, table="dir")
            with transact(con) as cur:
                if is_dir:
                    insert_dir_items(cur, attr)
                upsert_items(cur, attr)
        execute(
            con, 
            "INSERT OR IGNORE INTO life(id, data, create_time) VALUES (?,?,?)", 
            (int(event["id"]), dumps(event), create_time), 
            commit=True, 
        )
    raise


def updatedb_one(
    client: str | P115Client, 
    dbfile: None | str | Connection | Cursor = None, 
    id: int = 0, 
    /, 
    **request_kwargs, 
):
    """更新一个目录

    :param client: 115 网盘客户端对象
    :param dbfile: 数据库文件路径，如果为 None，则自动确定
    :param id: 要拉取的目录 id
    :param request_kwargs: 其它 http 请求参数，会传给具体的请求函数，默认的是 httpx，可用参数 request 进行设置

    :return: 2 元组，1) 已更替的数据列表，2) 已移除的 id 列表
    """
    client, con = _init_client(client, dbfile)
    to_upsert, to_remove = diff_dir(con, client, id, **request_kwargs)
    with transact(con) as cur:
        if to_upsert:
            upsert_items(cur, to_upsert)
        if to_remove:
            kill_items(cur, to_remove)
    return to_upsert, to_remove


def updatedb_tree(
    client: str | P115Client, 
    dbfile: None | str | Connection | Cursor = None, 
    id: int = 0, 
    /, 
    no_dir_moved: bool = True, 
    **request_kwargs, 
) -> tuple[list[dict], list[int]]:
    """更新一个目录树

    :param client: 115 网盘客户端对象
    :param dbfile: 数据库文件路径，如果为 None，则自动确定
    :param id: 要拉取的顶层目录 id
    :param no_dir_moved: 是否无目录被移动，如果为 True，则拉取会快一些
    :param request_kwargs: 其它 http 请求参数，会传给具体的请求函数，默认的是 httpx，可用参数 request 进行设置

    :return: 2 元组，1) 已更替的数据列表，2) 已移除的 id 列表
    """
    client, con = _init_client(client, dbfile)
    to_upsert, to_remove = diff_dir(con, client, id, tree=True, **request_kwargs)
    custom_no_dir_moved = no_dir_moved
    if id and to_remove:
        all_pids: set[int] = set()
        sql = "SELECT id, parent_id FROM data WHERE id IN (%s)" % (",".join(map(str, to_remove)) or "NULL")
        pairs = dict(query(con, sql))
        pids = set(pairs.values())
        while pids:
            all_pids.update(pids)
            if not custom_no_dir_moved:
                update_desc(client, pids, **request_kwargs)
                update_stared_dirs(con, client, **request_kwargs)
                no_dir_moved = True
            pids = {pid for pid in iter_parent_id(con, pids) if pid and pid != id and pid not in all_pids}
        if all_pids:
            na_ids = set(filter_na_ids(client, all_pids, **request_kwargs))
            for fid, pid in pairs.items():
                if pid in na_ids:
                    na_ids.add(fid)
                    continue
                ids = [fid, pid]
                while pid := get_parent_id(con, pid, 0):
                    if pid in na_ids:
                        na_ids.update(ids)
                        break
                    elif pid == id:
                        na_ids.add(fid)
                        break
                    ids.append(pid)
            to_remove = list(na_ids)
        else:
            to_remove = []
    if id and to_upsert:
        all_pids = set()
        pids = {ppid for attr in to_upsert if (ppid := attr["parent_id"])}
        while pids:
            all_pids.update(pids)
            if find_ids := pids - set(iter_existing_id(con, pids)):
                update_star(client, find_ids)
                if custom_no_dir_moved:
                    update_desc(client, find_ids, **request_kwargs)
                else:
                    update_desc(client, pids, **request_kwargs)
                update_stared_dirs(con, client, **request_kwargs)
                no_dir_moved = True
            elif not custom_no_dir_moved:
                update_desc(client, pids, **request_kwargs)
                no_dir_moved = False
            pids = {pid for pid in iter_parent_id(con, pids) if pid and pid != id and pid not in all_pids}
    if not no_dir_moved:
        update_stared_dirs(con, client, **request_kwargs)
    with transact(con) as cur:
        if to_remove:
            kill_items(cur, to_remove)
        if to_upsert:
            upsert_items(cur, to_upsert)
    return to_upsert, to_remove


def updatedb(
    client: str | P115Client, 
    dbfile: None | str | Connection | Cursor = None, 
    top_dirs: int | str | Iterable[int | str] = 0, 
    auto_splitting_threshold: int = 100_000, 
    auto_splitting_statistics_timeout: None | float = 3, 
    no_dir_moved: bool = True, 
    recursive: bool = True, 
    logger = logger, 
    disable_event: bool = False, 
    **request_kwargs, 
):
    """批量执行一组任务，任务为更新单个目录或者目录树的文件信息

    :param client: 115 网盘客户端对象
    :param dbfile: 数据库文件路径，如果为 None，则自动确定
    :param top_dirs: 要拉取的顶层目录集，可以是目录 id 或路径
    :param auto_splitting_threshold: 自动拆分任务时，仅当目录里面的总的文件和目录数大于此值才拆分任务，当 recursive 为 True 时生效
    :param auto_splitting_statistics_timeout: 自动拆分任务统计超时，当 recursive 为 True 时生效。如果超过此时间还不能确定目录里面的总的文件和目录数，则视为无穷大
    :param no_dir_moved: 是否无目录被移动，如果为 True，则拉取会快一些
    :param recursive: 是否递归拉取，如果为 True 则拉取目录树，否则只拉取一级目录
    :param logger: 日志对象，如果为 None，则不输出日志
    :param disable_event: 是否关闭 event 表的数据收集
    :param request_kwargs: 其它 http 请求参数，会传给具体的请求函数，默认的是 httpx，可用参数 request 进行设置
    """
    client, con = _init_client(client, dbfile, disable_event=disable_event)
    id_to_dirnode: dict = {}
    def parse_top_iter(top: int | str | Iterable[int | str], /) -> Iterator[int]:
        if isinstance(top, int):
            yield top
        elif isinstance(top, str):
            if top in ("", "0", ".", "..", "/"):
                yield 0
            elif not (top.startswith("0") or top.strip(digits)):
                yield int(top)
            else:
                try:
                    yield get_id_to_path(
                        client, 
                        top, 
                        ensure_file=False, 
                        app="android", 
                        id_to_dirnode=id_to_dirnode, 
                    )
                except FileNotFoundError:
                    if logger is not None:
                        logger.exception("[\x1b[1;31mFAIL\x1b[0m] directory not found: %r", top)
        else:
            for top_ in top:
                yield from parse_top_iter(top_)
    if not (top_ids := set(parse_top_iter(top_dirs))):
        return
    if (auto_splitting_statistics_timeout is None or 
        isnan(auto_splitting_statistics_timeout) or 
        isinf(auto_splitting_statistics_timeout) or 
        auto_splitting_statistics_timeout <= 0
    ):
        auto_splitting_statistics_timeout = None
    seen: set[int] = set()
    seen_add = seen.add
    need_calc_size = recursive and auto_splitting_threshold > 0
    if need_calc_size:
        executor = ThreadPoolExecutor(max_workers=1)
        submit = executor.submit
        cache_futures: dict[int, Future] = {}
        kwargs = {**request_kwargs, "timeout": auto_splitting_statistics_timeout}
        def get_dir_size(cid: int = 0, /) -> int | float:
            try:
                if cid:
                    kwargs["base_url"] = get_proapi()
                    resp = client.fs_category_get_app(cid, **kwargs)
                    if not resp:
                        return 0
                    check_response(resp)
                    return int(resp["count"])
                else:
                    resp = check_response(client.fs_space_summury(**kwargs))
                    if not resp["type_summury"]:
                        return float("inf")
                    return sum(v["count"] for k, v in resp["type_summury"].items() if k.isupper())
            except Exception as e:
                if is_timeouterror(e):
                    if logger is not None:
                        logger.info("[\x1b[1;37;43mSTAT\x1b[0m] \x1b[1m%d\x1b[0m, too big, since statistics timeout, consider the size as \x1b[1;3minf\x1b[0m", id)
                    return float("inf")
                raise
    try:
        if need_calc_size:
            for cid in top_ids:
                if cid not in cache_futures:
                    cache_futures[cid] = submit(get_dir_size, cid)
        gen = bfs_gen(iter(top_ids), unpack_iterator=True) # type: ignore
        send = gen.send
        for id in gen:
            if id in seen:
                if logger is not None:
                    logger.warning("[\x1b[1;33mSKIP\x1b[0m] already processed: %s", id)
                continue
            if auto_splitting_threshold == 0:
                need_to_split_tasks = True
            elif auto_splitting_threshold < 0:
                need_to_split_tasks = False
            elif recursive:
                count = cache_futures[id].result()
                if count <= 0:
                    seen_add(id)
                    continue
                need_to_split_tasks = count > auto_splitting_threshold
                if logger is not None:
                    if need_to_split_tasks:
                        logger.info(f"[\x1b[1;37;41mTELL\x1b[0m] \x1b[1m{id}\x1b[0m, \x1b[1;31mbig\x1b[0m ({count:,.0f} > {auto_splitting_threshold:,d}), will be pulled in \x1b[1;4;5;31mmulti batches\x1b[0m")
                    else:
                        logger.info(f"[\x1b[1;37;42mTELL\x1b[0m] \x1b[1m{id}\x1b[0m, \x1b[1;32mfit\x1b[0m ({count:,.0f} <= {auto_splitting_threshold:,d}), will be pulled in \x1b[1;4;5;32mone batch\x1b[0m")
            else:
                need_to_split_tasks = True
            try:
                start = perf_counter()
                if need_to_split_tasks or not recursive:
                    to_upsert, to_remove = updatedb_one(client, con, id, **request_kwargs)
                else:
                    if not no_dir_moved:
                        update_stared_dirs(con, client)
                        no_dir_moved = True
                    to_upsert, to_remove = updatedb_tree(client, con, id, **request_kwargs)
            except FileNotFoundError:
                kill_items(con, id, commit=True)
                if logger is not None:
                    logger.warning("[\x1b[1;33mSKIP\x1b[0m] not found: %s", id)
            except NotADirectoryError:
                if logger is not None:
                    logger.warning("[\x1b[1;33mSKIP\x1b[0m] not a directory: %s", id)
            except BusyOSError:
                if logger is not None:
                    logger.warning("[\x1b[1;35mREDO\x1b[0m] directory is busy updating: %s", id)
                send(id)
            except:
                if logger is not None:
                    logger.exception("[\x1b[1;31mFAIL\x1b[0m] %s", id)
                raise
            else:
                if logger is not None:
                    logger.info(
                        "[\x1b[1;32mGOOD\x1b[0m] \x1b[1m%s\x1b[0m, upsert: %d, remove: %d, cost: %.6f s", 
                        id, 
                        len(to_upsert), 
                        len(to_remove), 
                        perf_counter() - start, 
                    )
                seen_add(id)
                if recursive and need_to_split_tasks:
                    for cid in iter_descendants_fast(con, id, fields=False, ensure_file=False, max_depth=1):
                        send(cid)
                        if need_calc_size and cid not in cache_futures:
                            cache_futures[cid] = submit(get_dir_size, cid)
    finally:
        if need_calc_size:
            executor.shutdown(wait=False, cancel_futures=True)

# TODO: 增加一个选项，允许对数据进行全量而不是增量更新，这样可以避免一些问题
# TODO: 为数据库插入弄单独一个线程，就不需要等待数据库插入完成，就可以开始下一批数据拉取
# TODO: 再实现一个拉取数据的函数，只拉取文件数据，不拉取目录，只看更新时间，只要更新时间较新的，就写入数据库，只增改不删，如果是全新的，就用多线程（20线程），如果不是则从日期最新开始拉，如果一个目录太大，则临时找出所有子目录，再分拆，如果目标是文件，则直接把数据保存到数据库，然后停工（通过category_get获取）
# TODO: 为 115 生活单独做一个命令行命令
