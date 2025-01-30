#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__all__ = ["updatedb"]

import logging

from collections import deque
from collections.abc import Callable, Iterable
from math import inf
from sqlite3 import connect, Connection, Cursor
from string import digits
from time import sleep, time
from warnings import warn

from concurrenttools import run_as_thread
from iterutils import iter_unique
from orjson import dumps, loads
from p115client import P115Client
from p115client.exception import BusyOSError, P115Warning
from p115client.tool import iter_files, iter_fs_files, iter_nodes_skim, get_id_to_path, iter_parents_3_level
from sqlitetools import execute, find, upsert_items, AutoCloseConnection


logger = logging.Logger("115-updatedb-file", level=logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    "[\x1b[1m%(asctime)s\x1b[0m] (\x1b[1;36m%(levelname)s\x1b[0m) "
    "\x1b[0m\x1b[1;35m%(name)s\x1b[0m \x1b[5;31m➜\x1b[0m %(message)s"
))
logger.addHandler(handler)


def initdb(con: Connection | Cursor, /) -> Cursor:
    sql = """\
PRAGMA journal_mode = WAL;
-- 创建表
CREATE TABLE IF NOT EXISTS data (
    id INTEGER NOT NULL PRIMARY KEY,   -- 文件的 id
    pickcode TEXT NOT NULL DEFAULT '', -- 提取码，下载时需要用到
    sha1 TEXT NOT NULL DEFAULT '',     -- 文件的 sha1 散列值
    size INTEGER NOT NULL DEFAULT 0,   -- 文件大小
    name TEXT NOT NULL DEFAULT '',     -- 名字
    mtime INTEGER NOT NULL DEFAULT 0,  -- 更新时间戳
    is_collect INTEGER NOT NULL DEFAULT 0 CHECK(is_collect IN (0, 1)), -- 是否已被标记为违规
    parent_id INTEGER NOT NULL DEFAULT 0, -- 父目录 id
    parent_name TEXT NOT NULL DEFAULT '', -- 父目录名字
    parent_pickcode TEXT NOT NULL DEFAULT '', -- 父目录提取码
    top_id INTEGER NOT NULL DEFAULT 0, -- 上一次拉取时顶层目录的 id
    extra BLOB DEFAULT NULL -- 其它信息
);
-- 创建索引
CREATE INDEX IF NOT EXISTS idx_data_pc ON data(pickcode);
CREATE INDEX IF NOT EXISTS idx_data_sha1_size ON data(sha1, size);
CREATE INDEX IF NOT EXISTS idx_data_tid ON data(top_id);
CREATE INDEX IF NOT EXISTS idx_data_pid ON data(parent_id);
CREATE INDEX IF NOT EXISTS idx_data_name ON data(name);
CREATE INDEX IF NOT EXISTS idx_data_mtime ON data(mtime);
"""
    return con.executescript(sql)


def normalize_attr(info: dict, /) -> dict:
    """筛选和规范化数据的名字，以便插入 `data` 表

    :param info: 原始数据

    :return: 经过规范化后的数据
    """
    if "fn" in info:
        is_dir = info["fc"] == "0"
        attr = {
            "id": int(info["fid"]), 
            "pickcode": info["pc"], 
            "sha1": info.get("sha1") or "", 
            "size": int(info.get("fs") or 0), 
            "name": info["fn"], 
            "mtime": int(info["upt"]), 
            "is_collect": int(info.get("ic") or 0) == 1, 
            "parent_id": int(info["pid"]), 
        }
    elif "file_id" in info or "category_id" in info:
        is_dir = "file_id" not in info
        attr = {
            "id": int(info["category_id" if is_dir else "file_id"]), 
            "pickcode": info["pick_code"], 
            "sha1": info.get("sha1") or "", 
            "size": int(info.get("file_size") or 0), 
            "name": info["category_name" if is_dir else "file_name"], 
            "mtime": int(info["ptime" if is_dir else "user_ptime"]), 
            "is_collect": int(info.get("is_collect") or 0) == 1, 
            "parent_id": int(info["parent_id" if is_dir else "category_id"]), 
        }
    else:
        is_dir = "fid" not in info
        attr = {
            "id": int(info["cid" if is_dir else "fid"]), 
            "pickcode": info["pc"], 
            "sha1": info.get("sha") or "", 
            "size": int(info.get("s") or 0), 
            "name": info["n"], 
            "mtime": int(info.get("te") or 0), 
            "is_collect": int(info.get("c") or 0) == 1, 
            "parent_id": int(info["pid" if is_dir else "cid"]), 
        }
    return attr


def select_mtime_groups(
    con: Connection | Cursor, 
    top_id: int = 0, 
    /, 
) -> list[tuple[int, set[int]]]:
    """获取某个目录之下的节点（不含此节点本身），按 mtime 进行分组，相同 mtime 的 id 归入同一组

    :param con: 数据库连接或游标
    :param top_id: 顶层目录的 id

    :return: 元组的列表（逆序排列），每个元组第 1 个元素是 mtime，第 2 个元素是相同 mtime 的 id 的集合
    """
    sql = "SELECT id, mtime FROM data WHERE top_id = ? ORDER BY mtime DESC"
    ls: list[tuple[int, set[int]]] = []
    append = ls.append
    last_mtime = 0
    part_add: Callable
    for id, mtime in con.execute(sql, (top_id,)):
        if mtime == last_mtime:
            part_add(id)
        else:
            part = {id}
            append((mtime, part))
            part_add = part.add
            last_mtime = mtime
    return ls


def updatedb_all(
    client: P115Client, 
    con: Connection | Cursor, 
    top_id: int = 0, 
    page_size: int = 8_000, 
    max_workers: None | int = None, 
    with_parents: bool = False, 
) -> tuple[int, int]:
    def norm_attr(info: dict, /) -> dict:
        attr = normalize_attr(info)
        attr["top_id"] = top_id
        add_attr(attr)
        return attr
    ls_attr: list[dict] = []
    add_attr = ls_attr.append
    parent_nodes: dict[int, dict] = {}
    if not top_id:
        parent_nodes[0] = {"parent_name": "", "parent_pickcode": ""}
    for info in iter_nodes_skim(client, iter_unique(pid for attr in 
        iter_files(
            client, 
            top_id, 
            page_size=page_size, 
            normalize_attr=norm_attr, 
            id_to_dirnode=..., 
            raise_for_changed_count=True, 
            app="android", 
            cooldown=0.5, 
            max_workers=max_workers, 
        ) if (pid := attr["parent_id"])
    )):
        parent_nodes[int(info["file_id"])] = {
            "parent_name": info["file_name"], 
            "parent_pickcode": info["pick_code"], 
        }
    for attr in ls_attr:
        attr.update(parent_nodes[attr["parent_id"]])
    del parent_nodes
    upsert_items(con, ls_attr)
    if with_parents:
        parent_ids = {a["parent_id"] for a in ls_attr}
        sql = """\
UPDATE data 
SET extra=JSON_PATCH(
    COALESCE(extra, '{}'), 
    JSON_OBJECT('parents', JSONB(json_array_prepend(?, parent_name)))
)
WHERE parent_id=?"""
        con.executemany(sql, ((dumps(parents), pid) for pid, parents in iter_parents_3_level(client, parent_ids)))
    if isinstance(con, Cursor):
        con = con.connection
    con.commit()
    return len(ls_attr), 0


def updatedb_partial(
    client: P115Client, 
    con: Connection | Cursor, 
    top_id: int = 0, 
    page_size: int = 8_000, 
    no_dir_moved: bool = False, 
    with_parents: bool = False, 
) -> tuple[int, int]:
    upsert_list: list[dict] = []
    remove_list: list[int] = []
    try:
        future = run_as_thread(select_mtime_groups, con, top_id)
        upsert_add = upsert_list.append
        remove_extend = remove_list.extend
        seen: set[int] = set()
        seen_add = seen.add
        discard = set.discard
        n = 0
        for i, resp in enumerate(iter_fs_files(
            client, 
            {"asc": 0, "cid": top_id, "fc_mix": 1, "o": "user_utime", "show_dir": 0}, 
            first_page_size=64, 
            page_size=page_size, 
            app="android", 
            raise_for_changed_count=True, 
        )):
            if not i:
                groups = future.result()
                remains = sum(len(g[1]) for g in groups)
                his_it = iter(groups)
                his_mtime, his_ids = next(his_it)
            count = resp["count"]
            for n, info in enumerate(resp["data"], n + 1):
                attr = normalize_attr(info)
                cur_id = attr["id"]
                seen_add(cur_id)
                if remains:
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
                            raise StopIteration
                        discard(his_ids, cur_id)
                        continue
                attr["top_id"] = top_id
                upsert_add(attr)
            if remains:
                remove_extend(his_ids - seen)
                for _, his_ids in his_it:
                    remove_extend(his_ids - seen)
    except StopIteration:
        pass
    if remove_list:
        sql = "DELETE FROM data WHERE id IN (%s)" % ",".join(map(str, remove_list))
        con.execute(sql)
    if upsert_list:
        upsert_items(con, upsert_list)
    if no_dir_moved:
        parent_ids: Iterable[int] = {a["parent_id"] for a in upsert_list}
    else:
        sql = "SELECT DISTINCT parent_id FROM data WHERE top_id = ?"
        parent_ids = [pid for pid, in con.execute(sql, (top_id,))]
    sql = "UPDATE data SET parent_name=?, parent_pickcode=? WHERE parent_id=?"
    con.executemany(sql, (
        (info["file_name"], info["pick_code"], int(info["file_id"]))
        for info in iter_nodes_skim(client, parent_ids)
    ))
    if with_parents:
        sql = """\
UPDATE data 
SET extra=JSON_PATCH(
    COALESCE(extra, '{}'), 
    JSON_OBJECT('parents', JSONB(json_array_prepend(?, parent_name)))
)
WHERE parent_id=?"""
        con.executemany(sql, ((dumps(parents), pid) for pid, parents in iter_parents_3_level(client, parent_ids)))
    if isinstance(con, Cursor):
        con = con.connection
    con.commit()
    return len(upsert_list), len(remove_list)


def json_array_prepend(json_str, value):
    js = loads(json_str)
    js.insert(0, value)
    return dumps(js)


def _init_client(
    client: str | P115Client, 
    dbfile: None | str | Connection | Cursor = None, 
) -> tuple[P115Client, Connection | Cursor]:
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if (app := client.login_app()) in ("web", "desktop", "harmony"):
        warn(f'app within ("web", "desktop", "harmony") is not recommended, as it will retrieve a new "tv" cookies', category=P115Warning)
        client.login_another_app("tv", replace=True)
    if not dbfile:
        dbfile = f"115-file-{client.user_id}.db"
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
        initdb(con)
    if isinstance(con, Cursor):
        conn = con.connection
    else:
        conn = con
    conn.create_function("json_array_prepend", 2, json_array_prepend)
    return client, con


def updatedb(
    client: str | P115Client, 
    dbfile: None | str | Connection | Cursor = None, 
    top_dirs: int | str | Iterable[int | str] = 0, 
    page_size: int = 8_000, 
    no_dir_moved: bool = False, 
    with_parents: bool = False, 
    interval: int | float = 0, 
    max_workers: None | int = None, 
    logger = logger, 
):
    """批量执行一组任务，任务为更新单个目录或者目录树的文件信息

    :param client: 115 网盘客户端对象
    :param dbfile: 数据库文件路径，如果为 None，则自动确定
    :param top_dirs: 要拉取的顶层目录集，可以是目录 id 或路径
    :param page_size: 每次批量拉取的分页大小
    :param no_dir_moved: 是否无目录被移动或改名，如果为 True，则拉取会快一些
    :oaram with_parents: 是否给 extra 字段的 JSON，更新一个键为 "parents"，值为最近的 4 层上级目录
    :param interval: 两个任务之间的睡眠时间，如果 <= 0，则不睡眠
    :param max_workers: 全量更新时，最大的并发数
    :param logger: 日志对象，如果为 None，则不输出日志
    """
    if isinstance(top_dirs, (int, str)):
        top_dirs = top_dirs,
    dq = deque(top_dirs)
    get, put = dq.popleft, dq.append
    client, con = _init_client(client, dbfile)
    first_loop = True
    while dq:
        if first_loop and interval > 0:
            sleep(interval)
        first_loop = False
        top_dir = get()
        if isinstance(top_dir, int):
            top_id = top_dir
        else:
            if top_dir in ("", "0", ".", "..", "/"):
                top_id = 0
            elif not (top_dir.startswith("0") or top_dir.strip(digits)):
                top_id = int(top_dir)
            else:
                try:
                    top_id = get_id_to_path(
                        client, 
                        top_dir, 
                        ensure_file=False, 
                        app="android", 
                    )
                except FileNotFoundError:
                    if logger is not None:
                        logger.exception("[\x1b[1;31mFAIL\x1b[0m] directory not found: %r", top_dir)
                    continue
        start = time()
        try:
            if find(con, "SELECT 1 FROM data WHERE top_id = ?", top_id):
                upserted, removed = updatedb_partial(client, con, top_id, page_size, with_parents=with_parents, no_dir_moved=no_dir_moved)
            else:
                upserted, removed = updatedb_all(client, con, top_id, page_size, with_parents=with_parents, max_workers=max_workers)
        except FileNotFoundError:
            execute(con, "DELETE FROM data WHERE top_id = ?", top_id, commit=True)
            if logger is not None:
                logger.warning("[\x1b[1;33mSKIP\x1b[0m] not found: %s", top_id)
        except NotADirectoryError:
            if logger is not None:
                logger.warning("[\x1b[1;33mSKIP\x1b[0m] not a directory: %s", top_id)
        except BusyOSError:
            if logger is not None:
                logger.warning("[\x1b[1;35mREDO\x1b[0m] directory is busy updating: %s", top_id)
            put(top_id)
        except:
            if logger is not None:
                logger.exception("[\x1b[1;31mFAIL\x1b[0m] %s", top_id)
            raise
        else:
            if logger is not None:
                logger.info(
                    "[\x1b[1;32mGOOD\x1b[0m] \x1b[1m%s\x1b[0m, upsert: %d, remove: %d, cost: %.6f s", 
                    top_id, 
                    upserted, 
                    removed, 
                    time() - start, 
                )

