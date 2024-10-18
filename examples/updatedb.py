#!/usr/bin/env python3
# encoding: utf-8

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 5)
__all__ = ["updatedb", "updatedb_one", "updatedb_tree"]
__doc__ = "遍历 115 网盘的目录信息导出到数据库"
__requirements__ = ["orjson", "p115client", "posixpatht", "urllib3", "urllib3_request"]

if __name__ == "__main__":
    from argparse import ArgumentParser, RawTextHelpFormatter

    parser = ArgumentParser(
        formatter_class=RawTextHelpFormatter, 
        description=__doc__, 
    )
    parser.add_argument("top_dirs", metavar="dir", nargs="*", help="""\
115 目录，可以传入多个，如果不传默认为 0
允许 3 种类型的目录
    1. 整数，视为目录的 id
    2. 形如 "/名字/名字/..." 的路径，最前面的 "/" 可以省略，本程序会尝试获取对应的 id
    3. 形如 "根目录 > 名字 > 名字 > ..." 的路径，来自点击文件的【显示属性】，在【位置】这部分看到的路径，本程序会尝试获取对应的 id
""")
    parser.add_argument("-c", "--cookies", help="115 登录 cookies，优先级高于 -cp/--cookies-path")
    parser.add_argument("-cp", "--cookies-path", help="""\
存储 115 登录 cookies 的文本文件的路径，如果缺失，则从 115-cookies.txt 文件中获取，此文件可在如下目录之一: 
    1. 当前工作目录
    2. 用户根目录
    3. 此脚本所在目录
如果都找不到，则默认使用 '2. 用户根目录，此时则需要扫码登录'""")
    parser.add_argument("-f", "--dbfile", default="", help="sqlite 数据库文件路径，默认为在当前工作目录下的 f'115-{user_id}.db'")
    parser.add_argument("-cl", "--clean", action="store_true", help="任务完成后清理数据库，以节约空间")
    parser.add_argument("-st", "--auto-splitting-threshold", type=int, default=200_000, help="自动拆分的文件数阈值，大于此值时，自动进行拆分，如果 <= 0，则总是拆分，默认值 200,000（20 万）")
    parser.add_argument("-sst", "--auto-splitting-statistics-timeout", type=float, default=3, help="自动拆分前的执行文件数统计的超时时间（秒），大于此值时，视为文件数无穷大，如果 <= 0，视为永不超时，默认值 3")
    parser.add_argument("-nd", "--no-dir-moved", action="store_true", help="声明没有目录被移动或改名（但可以有目录被新增或删除），这可以加快批量拉取时的速度")
    parser.add_argument("-nr", "--not-recursive", action="store_true", help="不遍历目录树：只拉取顶层目录，不递归子目录")
    parser.add_argument("-r", "--resume", action="store_true", help="""中断重试，判断依据（满足如下条件之一）：
    1. 顶层目录未被采集：命令行所指定的某个 dir_id 的文件列表未被采集
    2. 目录未被采集：某个目录内的文件列表为空（可能为空，也可能未被采集）
    3. 目录更新至此：某个目录的文件信息的更新时间大于它里面的文件信息列表中更新时间最大的那一条
""")
    parser.add_argument("-v", "--version", action="store_true", help="输出版本号")

    args = parser.parse_args()
    if args.version:
        print(".".join(map(str, __version__)))
        raise SystemExit(0)

try:
    from orjson import dumps, loads
    from p115client import check_response, P115Client
    from p115client.exception import BusyOSError
    from p115client.tool.iterdir import ensure_attr_path, iter_stared_dirs, DirNode, DirNodeTuple
    from posixpatht import escape, joins, normpath
    from urllib3.poolmanager import PoolManager
    from urllib3.exceptions import ReadTimeoutError
    from urllib3_request import request as urllib3_request
except ImportError:
    from sys import executable
    from subprocess import run
    run([executable, "-m", "pip", "install", "-U", *__requirements__], check=True)
    from orjson import dumps, loads
    from p115client import check_response, P115Client
    from p115client.exception import BusyOSError
    from p115client.tool.iterdir import ensure_attr_path, iter_stared_dirs, DirNode, DirNodeTuple
    from posixpatht import escape, joins, normpath
    from urllib3.poolmanager import PoolManager
    from urllib3.exceptions import ReadTimeoutError
    from urllib3_request import request as urllib3_request

import logging

from collections import deque, ChainMap
from collections.abc import Callable, Collection, Iterator, Iterable, Mapping
from errno import EBUSY, ENOENT, ENOTDIR
from functools import partial
from itertools import islice
from math import isnan, isinf
from os.path import splitext
from sqlite3 import (
    connect, register_adapter, register_converter, Connection, Cursor, 
    Row, PARSE_COLNAMES, PARSE_DECLTYPES
)
from time import time
from typing import cast


ID_TO_DIRNODE: dict[int, DirNode | DirNodeTuple] = {}

request = partial(urllib3_request, pool=PoolManager(50))
register_adapter(list, dumps)
register_adapter(dict, dumps)
register_converter("JSON", loads)

logger = logging.Logger("115-updatedb", level=logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    "[\x1b[1m%(asctime)s\x1b[0m] (\x1b[1;36m%(levelname)s\x1b[0m) "
    "\x1b[0m\x1b[1;35m%(name)s\x1b[0m \x1b[5;31m➜\x1b[0m %(message)s"
))
logger.addHandler(handler)


def cut_iter(
    start: int, 
    stop: None | int = None, 
    step: int = 1, 
) -> Iterator[tuple[int, int]]:
    if stop is None:
        start, stop = 0, start
    for mid in range(start + step, stop, step):
        yield start, step
        start = mid
    if start < stop:
        yield start, stop - start


def normalize_path(path: str, /) -> int | str:
    if path in ("0", ".", "..", "/"):
        return 0
    if path.isdecimal():
        return int(path)
    if path.startswith("根目录 > "):
        patht = path.split(" > ")
        if len(patht) == 1:
            return 0
        patht[0] = ""
        return joins(patht)
    path = normpath("/" + path)
    if path == "/":
        return 0
    return path


def do_commit(
    con: Connection | Cursor, 
):
    conn = cast(Connection, getattr(con, "connection", con))
    conn.commit()


def execute_commit(
    con: Connection | Cursor, 
    /, 
    sql: str, 
    params = None, 
    executemany: bool = False, 
) -> Cursor:
    conn = cast(Connection, getattr(con, "connection", con))
    try:
        if executemany:
            cur = con.executemany(sql, params)
        elif params is None:
            cur = con.execute(sql)
        else:
            cur = con.execute(sql, params)
        conn.commit()
        return cur
    except BaseException:
        conn.rollback()
        raise


def json_array_head_replace(value, repl, stop=None):
    value = loads(value)
    repl  = loads(repl)
    if stop is None:
        stop = len(repl)
    value[:stop] = repl
    return dumps(value)


def initdb(con: Connection | Cursor, /) -> Cursor:
    conn = cast(Connection, getattr(con, "connection", con))
    conn.row_factory = Row
    conn.create_function("escape_name", 1, escape)
    conn.create_function("json_array_head_replace", 3, json_array_head_replace)
    return con.executescript("""\
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS data (
    id INTEGER NOT NULL PRIMARY KEY,
    parent_id INTEGER NOT NULL,
    pickcode TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    sha1 TEXT NOT NULL DEFAULT '',
    is_dir INTEGER NOT NULL CHECK(is_dir IN (0, 1)),
    is_image INTEGER NOT NULL CHECK(is_image IN (0, 1)) DEFAULT 0,
    ctime INTEGER NOT NULL DEFAULT 0,
    mtime INTEGER NOT NULL DEFAULT 0,
    path TEXT NOT NULL DEFAULT '',
    updated_at DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%S.%f+08:00', 'now', '+8 hours'))
);

CREATE TABLE IF NOT EXISTS dir (
    id INTEGER NOT NULL PRIMARY KEY,
    parent_id INTEGER NOT NULL,
    pickcode TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    ctime INTEGER NOT NULL DEFAULT 0,
    mtime INTEGER NOT NULL DEFAULT 0
);

CREATE TRIGGER IF NOT EXISTS trg_data_updated_at
AFTER UPDATE ON data 
FOR EACH ROW
BEGIN
    UPDATE data SET updated_at = strftime('%Y-%m-%dT%H:%M:%S.%f+08:00', 'now', '+8 hours') WHERE id = NEW.id;
END;

CREATE INDEX IF NOT EXISTS idx_data_parent_id ON data(parent_id);
CREATE INDEX IF NOT EXISTS idx_data_path ON data(path);
CREATE INDEX IF NOT EXISTS idx_dir_mtime ON dir(mtime);
""")


def load_id_to_dirnode(
    con: Connection | Cursor,
    /, 
    id_to_dirnode: None | dict[int, DirNode | DirNodeTuple] = None, 
) -> dict[int, DirNode | DirNodeTuple]:
    if id_to_dirnode is None:
        id_to_dirnode = ID_TO_DIRNODE
    sql = "SELECT id, name, parent_id FROM dir"
    for row in con.execute(sql):
        ID_TO_DIRNODE[row[0]] = cast(DirNodeTuple, (row[1], row[2]))
    return ID_TO_DIRNODE


def update_id_to_dirnode(
    con: Connection | Cursor, 
    /, 
    client: P115Client, 
    id_to_dirnode: None | dict[int, DirNode | DirNodeTuple] = None, 
):
    if id_to_dirnode is None:
        id_to_dirnode = ID_TO_DIRNODE
    sql = "SELECT MAX(mtime) FROM dir"
    mtime = con.execute(sql).fetchone()[0] or 0
    update_data = []
    for attr in iter_stared_dirs(client, order="user_utime", asc=0, first_page_size=128, normalize_attr=normalize_dir_attr):
        if attr["mtime"] < mtime:
            break
        ID_TO_DIRNODE[attr["id"]] = cast(DirNodeTuple, (attr["name"], attr["parent_id"]))
        update_data.append(attr)
    if update_data:
        insert_dir_items(con, update_data)


def select_ids_to_update(
    con: Connection | Cursor, 
    top_dirs: int | Iterable[int] = 0, 
    /, 
) -> Cursor:
    if isinstance(top_dirs, int):
        ids = "(%d)" % top_dirs
    else:
        ids = ",".join(map("(%d)".__mod__, top_dirs))
        if not ids:
            raise ValueError("no top_dirs specified")
    sql = f"""\
WITH top_dir_ids(id) AS (
    VALUES {ids}
), ids_to_update AS (
    SELECT
        d1.id, 
        d1.updated_at, 
        MAX(d2.updated_at) AS max_sub_updated_at
    FROM
        data d1 LEFT JOIN data d2 ON (d1.id=d2.parent_id)
    WHERE
        d1.is_dir
        AND d1.mtime
        AND (d2.mtime OR d2.id IS NULL)
    GROUP BY
        d1.id
    HAVING
        max_sub_updated_at IS NULL OR d1.updated_at > max_sub_updated_at
)
SELECT top.id FROM top_dir_ids AS top WHERE NOT EXISTS(SELECT 1 FROM data WHERE parent_id = top.id AND mtime)
UNION ALL
SELECT id FROM ids_to_update;
"""
    return con.execute(sql)


def select_subdir_ids(
    con: Connection | Cursor, 
    parent_id: int = 0, 
    /, 
) -> Cursor:
    sql = "SELECT id FROM data WHERE parent_id=? AND is_dir=1;"
    return con.execute(sql, (parent_id,))


def select_mtime_groups(
    con: Connection | Cursor, 
    parent_id: int = 0, 
    /, 
    tree: bool = False, 
) -> Cursor:
    if tree:
        sql = """\
WITH t AS (
    SELECT id, mtime, is_dir
    FROM data
    WHERE parent_id=?
    UNION ALL
    SELECT data.id, data.mtime, data.is_dir
    FROM t JOIN data ON (data.parent_id = t.id)
)
SELECT mtime, JSON_GROUP_ARRAY(id) AS "ids [JSON]"
FROM t
WHERE is_dir = 0
GROUP BY mtime
ORDER BY mtime DESC;
"""
    else:
        sql = """\
SELECT mtime, JSON_GROUP_ARRAY(id) AS "ids [JSON]"
FROM data
WHERE parent_id=? AND mtime != 0
GROUP BY mtime
ORDER BY mtime DESC;
"""
    return con.execute(sql, (parent_id,))


def insert_items(
    con: Connection | Cursor, 
    items: dict | Iterable[dict], 
    /, 
    commit: bool = True, 
    with_path: bool = False, 
) -> Cursor:
    sql = """\
INSERT INTO
    data(id, parent_id, pickcode, name, size, sha1, is_dir, is_image, ctime, path, mtime)
VALUES
    (:id, :parent_id, :pickcode, :name, :size, :sha1, :is_dir, :is_image, :ctime, :path, :mtime)
ON CONFLICT(id) DO UPDATE SET
    parent_id = excluded.parent_id,
    pickcode  = excluded.pickcode,
    name      = CASE WHEN data.is_dir THEN data.name ELSE excluded.name END,
    ctime     = excluded.ctime,
    mtime     = excluded.mtime,
    path      = excluded.path
WHERE
    mtime != excluded.mtime
"""
    if isinstance(items, dict):
        items = items,
    if commit:
        return execute_commit(con, sql, items, executemany=True)
    else:
        return con.executemany(sql, items)


def insert_dir_items(
    con: Connection | Cursor, 
    items: Mapping | Iterable[Mapping], 
    /, 
    commit: bool = True, 
) -> Cursor:
    sql = """\
INSERT INTO
    dir(id, parent_id, pickcode, name, ctime, mtime)
VALUES
    (:id, :parent_id, :pickcode, :name, :ctime, :mtime)
ON CONFLICT(id) DO UPDATE SET
    parent_id = excluded.parent_id,
    name      = excluded.name,
    mtime     = excluded.mtime
WHERE
    mtime != excluded.mtime
"""
    if isinstance(items, Mapping):
        items = items,
    if commit:
        return execute_commit(con, sql, items, executemany=True)
    else:
        return con.executemany(sql, items)


def insert_dir_items_without_mtime(
    con: Connection | Cursor, 
    items: Mapping | Iterable[Mapping], 
    /, 
    commit: bool = True, 
) -> Cursor:
    sql = """\
INSERT INTO
    dir(id, parent_id, name)
VALUES
    (:id, :parent_id, :name)
ON CONFLICT(id) DO UPDATE SET
    parent_id = excluded.parent_id,
    name      = excluded.name
"""
    if isinstance(items, Mapping):
        items = items,
    if commit:
        return execute_commit(con, sql, items, executemany=True)
    else:
        return con.executemany(sql, items)


def delete_items(
    con: Connection | Cursor, 
    ids: int | Iterable[int], 
    /, 
    commit: bool = True, 
) -> Cursor:
    if isinstance(ids, int):
        cond = f"id = {ids:d}"
    else:
        cond = "id IN (%s)" % (",".join(map(str, ids)) or "NULL")
    sql = "DELETE FROM data WHERE " + cond
    if commit:
        return execute_commit(con, sql)
    else:
        return con.execute(sql)


def update_files_time(
    con: Connection | Cursor, 
    parent_id: int = 0, 
    /, 
    commit: bool = True, 
) -> Cursor:
    sql = """\
UPDATE data
SET updated_at = strftime('%Y-%m-%dT%H:%M:%S.%f+08:00', 'now', '+8 hours')
WHERE parent_id = ?;
"""
    if commit:
        return execute_commit(con, sql, (parent_id,))
    else:
        return con.execute(sql, (parent_id,))


def update_path(
    con: Connection | Cursor, 
    /, 
    commit: bool = True, 
) -> tuple[Cursor, int]:
    sql = """\
WITH RECURSIVE t(id, parent_id, path) AS (
    SELECT
        id, 
        data.parent_id, 
        '/' || escape_name(data.name)
    FROM
        data JOIN dir USING (id)
    WHERE
        data.name != dir.name
        OR data.parent_id != dir.parent_id
    UNION ALL
    SELECT
        t.id, 
        data.parent_id, 
        '/' || escape_name(data.name) || t.path
    FROM
        t JOIN data ON (t.parent_id=data.id)
)
SELECT id, path 
FROM t 
WHERE parent_id = 0
ORDER BY path DESC;
"""
    def get_path(cid):
        path = ""
        while cid:
            name, cid = ID_TO_DIRNODE[cid]
            path = "/" + escape(name) + path
        return path
    if isinstance(con, Connection):
        cur = con.cursor()
    else:
        cur = con
    change = 0
    for cid, path in con.execute(sql):
        path_new = get_path(cid)
        cur.execute("UPDATE data SET name=?, path=? WHERE id=?", (ID_TO_DIRNODE[cid][0], path_new, cid))
        cur.execute("UPDATE data SET path = ? || SUBSTR(path, ?) WHERE path LIKE ? || '/%'", (path_new, len(path) + 1, path))
        change += cur.rowcount + 1
    if commit:
        cur.connection.commit()
    return cur, change


def find_dangling_ids(
    con: Connection | Cursor, 
    /, 
) -> set[int]:
    d = dict(con.execute("SELECT id, parent_id FROM data;"))
    temp: list[int] = []
    ok_ids: set[int] = set()
    na_ids: set[int] = set()
    push = temp.append
    clear = temp.clear
    update_ok = ok_ids.update
    update_na = na_ids.update
    for k, v in d.items():
        try:
            push(k)
            while k := d[k]:
                if k in ok_ids:
                    update_ok(temp)
                    break
                elif k in na_ids:
                    update_na(temp)
                    break
                push(k)
            else:
                update_ok(temp)
        except KeyError:
            update_na(temp)
        finally:
            clear()
    return na_ids


def clear_invalid_dirs(
    con, 
    /, 
    client: P115Client, 
    commit: bool = True, 
):
    """删除无效的目录，也就是数据库中存在，但是网盘中不存在的目录
    """
    sql = """\
SELECT
    data.id
FROM
    data LEFT JOIN data AS data2 ON (data.id = data2.parent_id)
WHERE
    data.is_dir AND data2.id IS NULL;
"""
    ids = [row[0] for row in con.execute(sql)]
    na_ids = []
    for i in range(0, len(ids), 100_000):
        part = ids[i:i+100_000]
        resp = client.fs_file_skim(part, request=request)
        if resp.get("error") == "文件不存在":
            na_ids.extend(part)
        else:
            check_response(resp)
            s = {int(a["file_id"]) for a in resp["data"]}
            na_ids.extend(id for id in part if id not in s)
    return delete_items(con, na_ids, commit=commit)


def clear_dangling_items(
    con: Connection | Cursor, 
    /, 
    commit: bool = True, 
) -> Cursor:
    """删除悬空的元素，所谓悬空，意指通过 paren_id 往上找寻，存在某个 paren_id != 0 且不在数据库中，然后这个 parent_id 之下的子树整个都要被移除
    """
    return delete_items(con, find_dangling_ids(con), commit=commit)


def normalize_attr(info: dict, /) -> dict:
    is_dir = "fid" not in info
    if is_dir:
        attr: dict = {"id": int(info["cid"]), "parent_id": int(info["pid"])}
    else:
        attr = {"id": int(info["fid"]), "parent_id": int(info["cid"])}
    attr["pickcode"] = info["pc"]
    attr["name"] = info["n"]
    attr["size"] = info.get("s") or 0
    attr["sha1"] = info.get("sha") or ""
    attr["is_dir"] = is_dir
    attr["is_image"] = not is_dir and bool(info.get("u"))
    attr["ctime"] = int(info.get("tp", 0))
    attr["mtime"] = int(info.get("te", 0))
    return attr


def normalize_dir_attr(info: dict, /) -> dict:
    return {
        "id": int(info["cid"]), 
        "parent_id": int(info["pid"]), 
        "pickcode": info["pc"], 
        "name": info["n"], 
        "ctime": int(info["tp"]), 
        "mtime": int(info["te"]), 
    }


# TODO: 如果发生 id 重复，但 count 没变，则并不报错，会丢弃重复的 id，并增加计数器，等拉取完后，从头部再开始再取一次（每取出一个未见到过的元素，计数器减 1，直到计数器为 0）
# TODO: 每次都要记录上一次的头部元素是哪个，因为可能反复要从头部开始，去追更，直到把所有更新都找全（如果找到上次的头部时，未遇到重复id，而计数器不为 0，则报错）
def iterdir(
    client: P115Client, 
    id: int = 0, 
    /, 
    page_size: int = 10_000, 
    payload: dict = {}, 
) -> tuple[int, list[dict], dict[int, dict], Iterator[dict]]:
    if page_size <= 0:
        page_size = 10_000
    payload = {
        "asc": 0, "cid": id, "custom_order": 1, "fc_mix": 1, "limit": min(16, page_size), 
        "show_dir": 1, "o": "user_utime", "offset": 0, **payload, 
    }
    fs_files = client.fs_files
    count = -1
    ancestors = [{"id": 0, "parent_id": 0, "name": ""}]
    seen: dict[int, dict] = {}
    def get_files():
        nonlocal count
        resp = check_response(fs_files(payload, request=request))
        if int(resp["path"][-1]["cid"]) != id:
            if count < 0:
                raise NotADirectoryError(ENOTDIR, f"not a dir or deleted: cid={id}")
            else:
                raise FileNotFoundError(ENOENT, f"no such dir: cid={id}")
        ancestors[1:] = (
            {"id": int(info["cid"]), "parent_id": int(info["pid"]), "name": info["name"]} 
            for info in resp["path"][1:]
        )
        if count < 0:
            count = resp["count"]
        elif count != resp["count"]:
            raise BusyOSError(EBUSY, f"detected count changes during iteration: cid={id}")
        return resp
    resp = get_files()
    def iter():
        nonlocal resp
        offset = 0
        payload["limit"] = page_size
        while True:
            for attr in map(normalize_attr, resp["data"]):
                if attr["id"] in seen:
                    raise BusyOSError(EBUSY, f"duplicate id found, means that some unpulled child elements have been updated: cid={id}")
                seen[attr["id"]] = attr
                yield attr
            offset += len(resp["data"])
            if offset >= count:
                break
            payload["offset"] = offset
            resp = get_files()
    return count, ancestors, seen, iter()


def diff_dir(
    con: Connection | Cursor, 
    client: P115Client, 
    id: int = 0, 
    /, 
    tree: bool = False, 
):
    n = 0
    saved: dict[int, set[int]] = {}
    for mtime, ls in select_mtime_groups(con, id, tree=tree):
        if isinstance(ls, (bytes, str)):
            ls = loads(ls)
        saved[mtime] = set(ls)
        n += len(ls)

    replace_list: list[dict] = []
    delete_list: list[int] = []
    if tree:
        count, ancestors, seen, data_it = iterdir(client, id, payload={"type": 99})
    else:
        count, ancestors, seen, data_it = iterdir(client, id)
    dirs: list[dict] = ancestors[1:]
    try:
        if not n:
            replace_list.extend(data_it)
            return delete_list, replace_list
        it = iter(saved.items())
        his_mtime, his_ids = next(it)
        for attr in data_it:
            if attr["is_dir"]:
                dirs.append(attr)
            cur_id = attr["id"]
            cur_mtime = attr["mtime"]
            while his_mtime > cur_mtime:
                delete_list.extend(his_ids - seen.keys())
                n -= len(his_ids)
                if not n:
                    replace_list.append(attr)
                    replace_list.extend(data_it)
                    return delete_list, replace_list
                his_mtime, his_ids = next(it)
            if his_mtime == cur_mtime:
                if cur_id in his_ids:
                    n -= 1
                    if count - len(seen) == n:
                        return delete_list, replace_list
                    his_ids.remove(cur_id)
            else:
                replace_list.append(attr)
        for _, his_ids in it:
            delete_list.extend(his_ids - seen.keys())
        return delete_list, replace_list
    finally:
        if dirs:
            insert_dir_items_without_mtime(con, dirs)


def updatedb_one(
    client: str | P115Client, 
    dbfile: None | str | Connection | Cursor = None, 
    id: int = 0, 
    /, 
):
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if not dbfile:
        dbfile = f"115-{client.user_id}.db"
    if isinstance(dbfile, (Connection, Cursor)):
        con = dbfile
        try:
            start = time()
            to_delete, to_replace = diff_dir(con, client, id)
        except BaseException as e:
            logger.exception("[\x1b[1;31mFAIL\x1b[0m] %s", id)
            if isinstance(e, (FileNotFoundError, NotADirectoryError)):
                delete_items(con, id)
            raise
        else:
            if to_delete:
                delete_items(con, to_delete, commit=False)
            if to_replace:
                ensure_attr_path(client, to_replace, with_path=True, id_to_dirnode=ID_TO_DIRNODE)
                insert_items(con, to_replace, commit=False)
            _, updated = update_path(con, commit=False)
            update_files_time(con, id, commit=False)
            do_commit(con)
            logger.info(
                "[\x1b[1;32mGOOD\x1b[0m] %s, upsert: %d, update_path: %d, delete: %d, cost: %.6f s", 
                id, 
                len(to_replace), 
                updated, 
                len(to_delete), 
                time() - start, 
            )
    else:
        with connect(
            dbfile, 
            detect_types=PARSE_DECLTYPES|PARSE_COLNAMES, 
            uri=dbfile.startswith("file:"), 
        ) as con:
            initdb(con)
            load_id_to_dirnode(con)
            updatedb_one(client, con, id)


def updatedb_tree(
    client: str | P115Client, 
    dbfile: None | str | Connection | Cursor = None, 
    id: int = 0, 
    /, 
    no_dir_moved: bool = False, 
):
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if not dbfile:
        dbfile = f"115-{client.user_id}.db"
    if isinstance(dbfile, (Connection, Cursor)):
        con = dbfile
        try:
            start = time()
            to_delete, to_replace = diff_dir(con, client, id, tree=True)
            if not no_dir_moved:
                update_id_to_dirnode(con, client)
            if to_replace:
                all_pids: set[int] = set()
                pids = {attr["parent_id"] for attr in to_replace if attr["parent_id"]}
                while pids:
                    all_pids.update(pids)
                    if find_ids := pids - ID_TO_DIRNODE.keys():
                        ids_it = iter(find_ids)
                        while ids := ",".join(map(str, islice(ids_it, 10_000))):
                            check_response(client.fs_star_set(ids, request=request))
                            check_response(client.fs_desc_set(ids, request=request))
                        update_id_to_dirnode(con, client)
                    pids = {ppid for pid in pids if (ppid := ID_TO_DIRNODE[pid][1])}
                fields = ("id", "parent_id", "pickcode", "name", "ctime", "mtime", "size", "sha1", "is_dir", "is_image")
                sql = """\
    SELECT id, parent_id, pickcode, name, ctime, mtime, 0 AS size, '' AS sha1, 1 AS is_dir, 0 AS is_image 
    FROM dir WHERE id in (%s)""" % ",".join(map('%d'.__mod__, all_pids))
                to_replace.extend(dict(zip(fields, row)) for row in con.execute(sql))
                ensure_attr_path(client, to_replace, with_path=True, id_to_dirnode=ID_TO_DIRNODE)
        except BaseException as e:
            logger.exception("[\x1b[1;31mFAIL\x1b[0m] %s", id)
            if isinstance(e, (FileNotFoundError, NotADirectoryError)):
                delete_items(con, id)
            raise
        else:
            if to_delete:
                delete_items(con, to_delete, commit=False)
            if to_replace:
                insert_items(con, to_replace, commit=False)
            _, updated = update_path(con, commit=False)
            update_files_time(con, id, commit=False)
            do_commit(con)
            logger.info(
                "[\x1b[1;32mGOOD\x1b[0m] %s, upsert: %d, update_path: %d, delete: %d, cost: %.6f s", 
                id, 
                len(to_replace), 
                updated, 
                len(to_delete), 
                time() - start, 
            )
    else:
        with connect(
            dbfile, 
            detect_types=PARSE_DECLTYPES|PARSE_COLNAMES, 
            uri=dbfile.startswith("file:"), 
        ) as con:
            initdb(con)
            load_id_to_dirnode(con)
            updatedb_tree(client, con, id, no_dir_moved=no_dir_moved)


def updatedb(
    client: str | P115Client, 
    dbfile: None | str | Connection | Cursor = None, 
    top_dirs: int | str | Iterable[int | str] = 0, 
    auto_splitting_threshold: int = 20_0000, 
    auto_splitting_statistics_timeout: None | float = 3, 
    no_dir_moved: bool = False, 
    recursive: bool = True, 
    resume: bool = False, 
    clean: bool = False, 
):
    if isinstance(client, str):
        client = P115Client(client, check_for_relogin=True)
    if not dbfile:
        dbfile = f"115-{client.user_id}.db"
    if (auto_splitting_statistics_timeout is None or 
        isnan(auto_splitting_statistics_timeout) or 
        isinf(auto_splitting_statistics_timeout) or 
        auto_splitting_statistics_timeout <= 0
    ):
        auto_splitting_statistics_timeout = None
    if isinstance(dbfile, (Connection, Cursor)):
        con = dbfile
        seen: set[int] = set()
        seen_add = seen.add
        dq: deque[int] = deque()
        push, pop = dq.append, dq.popleft
        if isinstance(top_dirs, int):
            top_ids: Collection[int] = (top_dirs,)
        elif isinstance(top_dirs, str):
            top_dir = normalize_path(top_dirs)
            if isinstance(top_dir, int):
                top_ids = (top_dir,)
            else:
                try:
                    resp = check_response(client.fs_dir_getid(top_dir, request=request))
                    if not resp["id"]:
                        return
                    top_ids = (int(resp["id"]),)
                except:
                    logger.exception("[\x1b[1;31mFAIL\x1b[0m] %r", top_dirs)
                    return
        else:
            top_ids = set()
            add_id = top_ids.add
            for top_dir in top_dirs:
                if isinstance(top_dir, int):
                    add_id(top_dir)
                else:
                    top_dir = normalize_path(top_dir)
                    if isinstance(top_dir, int):
                        add_id(top_dir)
                    else:
                        try:
                            resp = check_response(client.fs_dir_getid(top_dir, request=request))
                            if not resp["id"]:
                                continue
                            add_id(int(resp["id"]))
                        except:
                            logger.exception("[\x1b[1;31mFAIL\x1b[0m] %r", top_dir)
                            continue
            if not top_ids:
                return
        if resume:
            dq.extend(r[0] for r in select_ids_to_update(con, top_ids))
        else:
            dq.extend(top_ids)
        while dq:
            id = pop()
            if id in seen:
                logger.warning("[\x1b[1;33mSKIP\x1b[0m]", id)
                continue
            if auto_splitting_threshold <= 0:
                need_to_split_tasks = True
            else:
                if id == 0:
                    resp = check_response(client.fs_space_summury(request=request))
                    count = sum(v["count"] for k, v in resp["type_summury"].items() if k.isupper())
                else:
                    try:
                        resp = client.fs_category_get(id, timeout=auto_splitting_statistics_timeout, request=request)
                        if not resp:
                            seen_add(id)
                            continue
                        check_response(resp)
                        count = int(resp["count"])
                    except ReadTimeoutError:
                        count = float("inf")
                need_to_split_tasks = count > auto_splitting_threshold
            try:
                if not recursive or need_to_split_tasks:
                    updatedb_one(client, con, id)
                else:
                    updatedb_tree(client, con, id, no_dir_moved=no_dir_moved)
            except (FileNotFoundError, NotADirectoryError):
                pass
            except BusyOSError:
                logger.warning("[\x1b[1;34mREDO\x1b[0m] %s", id)
                push(id)
            else:
                seen_add(id)
                if recursive and need_to_split_tasks:
                    dq.extend(r[0] for r in select_subdir_ids(con, id))
        if clean and top_ids:
            clear_invalid_dirs(con, client)
            clear_dangling_items(con)
    else:
        with connect(
            dbfile, 
            detect_types=PARSE_DECLTYPES|PARSE_COLNAMES, 
            uri=dbfile.startswith("file:"), 
        ) as con:
            initdb(con)
            load_id_to_dirnode(con)
            updatedb(
                client, 
                con, 
                top_dirs=top_dirs, 
                auto_splitting_threshold=auto_splitting_threshold, 
                auto_splitting_statistics_timeout=auto_splitting_statistics_timeout, 
                no_dir_moved=no_dir_moved, 
                recursive=recursive, 
                resume=resume, 
                clean=clean, 
            )
            if clean:
                con.execute("PRAGMA wal_checkpoint;")
                con.execute("VACUUM;")


if __name__ == "__main__":
    if args.cookies:
        cookies = args.cookies
    else:
        from pathlib import Path

        if args.cookies_path:
            cookies = Path(args.cookies_path).absolute()
        else:
            for path in (
                Path("./115-cookies.txt").absolute(), 
                Path("~/115-cookies.txt").expanduser(), 
                Path(__file__).parent / "115-cookies.txt", 
            ):
                if path.is_file():
                    cookies = path
            else:
                cookies = Path("~/115-cookies.txt").expanduser()
    client = P115Client(cookies, check_for_relogin=True)
    updatedb(
        client, 
        dbfile=args.dbfile, 
        auto_splitting_threshold=args.auto_splitting_threshold, 
        auto_splitting_statistics_timeout=args.auto_splitting_statistics_timeout, 
        no_dir_moved=args.no_dir_moved, 
        recursive=not args.not_recursive, 
        resume=args.resume, 
        top_dirs=args.top_dirs or 0, 
        clean=args.clean, 
    )

# NOTE: 以下这些是待实现的设想 👇
# TODO: 作为模块提供，允许全量更新(updatedb)和增量更新(updatedb_one)，但只允许同时最多一个写入任务
# TODO: 可以起一个服务，其它的程序，可以发送读写任务过来，数据库可以以 fuse 或 webdav 展示
# TODO: 支持多个不同登录设备并发
# TODO: 支持同一个 cookies 并发因子，默认值 1
# TODO: 使用协程进行并发，而非多线程
# TODO: 如果请求超时，则需要进行重试
# TODO: sqlite 的数据库事务和写入会自动加锁，如果有多个程序在并发，则可以等待锁，需要一个超时时间和重试次数
# TODO: iterdir 函数支持并发
