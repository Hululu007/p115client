#!/usr/bin/env python3
# encoding: utf-8

from __future__ import annotations

__author__ = "ChenyangGao <https://chenyanggao.github.io>"
__version__ = (0, 0, 0)
__all__ = ["make_application"]
__doc__ = """\
115 数据库 WebDAV 服务，请先用 updatedb.py 采集数据
"""
__requirements__ = ["flask", "Flask-Compress", "p115client", "pyyaml", "urllib3", "urllib3_request", "werkzeug", "wsgidav"]

if __name__ == "__main__":
    from argparse import ArgumentParser, RawTextHelpFormatter

    parser = ArgumentParser(formatter_class=RawTextHelpFormatter, description=__doc__)
    parser.add_argument("dbfile", help="数据库路径")
    parser.add_argument("-c", "--config-path", help="""webdav 配置文件路径，采用 yaml 格式，如需样板文件，请阅读：

    https://wsgidav.readthedocs.io/en/latest/user_guide_configure.html#sample-wsgidav-yaml

""")
    parser.add_argument("-cp", "--cookies-path", default="", help="cookies 文件保存路径，默认是此脚本同一目录下的 115-cookies.txt")
    parser.add_argument("-H", "--host", default="0.0.0.0", help="ip 或 hostname，默认值：'0.0.0.0'")
    parser.add_argument("-P", "--port", default=8000, type=int, help="端口号，默认值：8000")
    parser.add_argument("-d", "--debug", action="store_true", help="启用 debug 模式，当文件变动时自动重启 + 输出详细的错误信息")
    parser.add_argument("-v", "--version", action="store_true", help="输出版本号")

    args = parser.parse_args()
    if args.version:
        print(".".join(map(str, __version__)))
        raise SystemExit(0)

try:
    from flask import redirect, request, url_for, Flask
    from flask_compress import Compress
    from p115client import P115Client
    from urllib3.poolmanager import PoolManager
    from urllib3_request import request as urllib3_request
    from werkzeug.middleware.dispatcher import DispatcherMiddleware
    from wsgidav.wsgidav_app import WsgiDAVApp
    from wsgidav.dav_error import DAVError
    from wsgidav.dav_provider import DAVCollection, DAVNonCollection, DAVProvider
    from wsgidav.server.server_cli import SUPPORTED_SERVERS
    from yaml import load, Loader
except ImportError:
    from sys import executable
    from subprocess import run
    run([executable, "-m", "pip", "install", "-U", *__requirements__], check=True)
    from flask import redirect, request, Flask
    from flask_compress import Compress # type: ignore
    from p115client import P115Client
    from urllib3.poolmanager import PoolManager
    from urllib3_request import request as urllib3_request
    from werkzeug.middleware.dispatcher import DispatcherMiddleware
    from wsgidav.wsgidav_app import WsgiDAVApp # type: ignore
    from wsgidav.dav_error import DAVError # type: ignore
    from wsgidav.dav_provider import DAVCollection, DAVNonCollection, DAVProvider # type: ignore
    from wsgidav.server.server_cli import SUPPORTED_SERVERS # type: ignore
    from yaml import load, Loader

from functools import cached_property, partial
from pathlib import Path
from posixpath import splitext
from sqlite3 import connect, Connection, OperationalError
from threading import Lock


def make_application(
    dbfile: str | Path, 
    config_path: str | Path = "", 
    cookies_path: str | Path = "", 
):
    FIELDS = ("id", "name", "ctime", "mtime", "size", "pickcode", "is_dir")
    if config_path:
        config = load(open(config_path, encoding="utf-8"), Loader=Loader)
    else:
        config = {"simple_dc": {"user_mapping": {"*": True}}}
    if cookies_path:
        cookies_path = Path(cookies_path)
    else:
        cookies_path = Path(__file__).parent / "115-cookies.txt"
    client = P115Client(cookies_path, app="harmony", check_for_relogin=True)
    urlopen = partial(urllib3_request, pool=PoolManager(num_pools=50))
    write_lock = Lock()

    class DavPathBase:

        def __getattr__(self, attr, /):
            try:
                return self.attr[attr]
            except KeyError as e:
                raise AttributeError(attr) from e

        @cached_property
        def creationdate(self, /) -> float:
            return self.ctime

        @cached_property
        def ctime(self, /) -> float:
            return self.attr["ctime"]

        @cached_property
        def mtime(self, /) -> float:
            return self.attr["mtime"]

        @cached_property
        def name(self, /) -> str:
            return self.attr["name"]

        def get_creation_date(self, /) -> float:
            return self.ctime

        def get_display_name(self, /) -> str:
            return self.name

        def get_etag(self, /) -> str:
            return "%s-%s-%s" % (
                self.attr["pickcode"], 
                self.mtime, 
                self.size, 
            )

        def get_last_modified(self, /) -> float:
            return self.mtime

        def is_link(self, /) -> bool:
            return False

        def support_etag(self, /) -> bool:
            return True

        def support_modified(self, /) -> bool:
            return True

    class FileResource(DavPathBase, DAVNonCollection):

        def __init__(
            self, 
            /, 
            path: str, 
            environ: dict, 
            attr: dict, 
            con: Connection, 
        ):
            super().__init__(path, environ)
            self.attr = attr
            self.con = con

        @cached_property
        def size(self, /) -> int:
            return self.attr["size"]

        @cached_property
        def url(self, /) -> str:
            scheme = self.environ["wsgi.url_scheme"]
            host = self.environ["HTTP_HOST"]
            return f"{scheme}://{host}?pickcode={self.attr['pickcode']}"

        def get_content(self, /):
            con = self.con
            fid = self.attr["id"]
            try:
                return con.blobopen("data", "data", fid, readonly=True, name="file")
            except (OperationalError, SystemError):
                pass
            if self.attr["size"] >= 1024 * 64:
                raise DAVError(302, add_headers=[("Location", self.url)])
            con.execute("""\
INSERT INTO file.data(id, data) VALUES(?, zeroblob(?)) 
ON CONFLICT(id) DO UPDATE SET data=excluded.data;""", (fid, self.attr["size"]))
            con.commit()
            try:
                data = urlopen(self.url).read()
                with write_lock:
                    with con.blobopen("data", "data", fid, name="file") as fdst:
                        fdst.write(data)
                return con.blobopen("data", "data", fid, readonly=True, name="file")
            except:
                con.execute("DELETE FROM file WHERE id=?", (fid,))
                con.commit()
                raise

        def get_content_length(self, /) -> int:
            return self.size

        def support_content_length(self, /) -> bool:
            return True

        def support_ranges(self, /) -> bool:
            return True

    class FolderResource(DavPathBase, DAVCollection):

        def __init__(
            self, 
            /, 
            path: str, 
            environ: dict, 
            attr: dict, 
            con: Connection, 
        ):
            super().__init__(path, environ)
            self.attr = attr
            self.con = con

        @cached_property
        def children(self, /) -> dict[str, dict]:
            sql = """\
SELECT id, name, ctime, mtime, size, pickcode, is_dir
FROM data
WHERE parent_id = :id AND name NOT IN ('', '.', '..') AND name NOT LIKE '%/%';
"""
            cur = self.con.execute(sql, self.attr)
            return {attr["name"]: attr for attr in (dict(zip(FIELDS, r)) for r in cur)}

        def get_member(self, /, name: str) -> FileResource | FolderResource:
            con = self.con
            path = self.path
            if path.endswith("/"):
                path += name
            else:
                path += "/" + name
            if not (attr := self.children.get(name)):
                raise DAVError(404, path)
            if attr["is_dir"]:
                return FolderResource(path, self.environ, attr, con)
            else:
                return FileResource(path, self.environ, attr, con)

        def get_member_list(self, /) -> list[FileResource | FolderResource]:
            return list(map(self.get_member, self.get_member_names()))

        def get_member_names(self, /) -> list[str]:
            return list(self.children)

        def get_property_value(self, /, name: str):
            if name == "{DAV:}getcontentlength":
                return 0
            elif name == "{DAV:}iscollection":
                return True
            return super().get_property_value(name)

    class ServeDBProvider(DAVProvider):

        def __init__(self, /, dbfile: str | Path):
            con = self.con = connect(dbfile, check_same_thread=False)
            dbfile = con.execute("SELECT file FROM pragma_database_list() WHERE name='main';").fetchone()[0]
            head, suffix = splitext(dbfile)
            con.execute("ATTACH DATABASE ? AS file;", (f"{head}-file{suffix}",))
            con.execute("""\
CREATE TABLE IF NOT EXISTS file.data (
    id INTEGER NOT NULL PRIMARY KEY,
    data BLOB,
    temp_path TEXT
);""")

        def __del__(self, /):
            try:
                self.con.close()
            except AttributeError:
                pass

        def get_resource_inst(
            self, 
            /, 
            path: str, 
            environ: dict, 
        ) -> FolderResource | FileResource:
            con = self.con
            if path in ("/", ""):
                return FolderResource(
                    "/", 
                    environ, 
                    {"id": 0, "name": "", "ctime": 0, "mtime": 0, "size": 0, "pickcode": "", "is_dir": 1}, 
                    con
                )
            path = path.removesuffix("/")
            sql = "SELECT id, name, ctime, mtime, size, pickcode, is_dir FROM data WHERE path = ? LIMIT 1"
            cur = con.execute(sql, (path,))
            record = cur.fetchone()
            if not record:
                raise DAVError(404, path)
            attr = dict(zip(FIELDS, record))
            if attr["is_dir"]:
                return FolderResource(path, environ, attr, con)
            else:
                return FileResource(path, environ, attr, con)

        def is_readonly(self, /) -> bool:
            return True

    flask_app = Flask(__name__)
    Compress(flask_app)

    @flask_app.route("/", methods=["GET", "HEAD"])
    def index():
        if pickcode := request.args.get("pickcode"):
            resp = client.download_url_app(
                pickcode, 
                headers={"User-Agent": request.headers.get("User-Agent") or ""}, 
                request=urlopen, 
            )
            return redirect(next(iter(resp["data"].values()))["url"]["url"])
        else:
            return redirect("/d")

    @flask_app.route("/", methods=[
        "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", 
        "TRACE", "PATCH", "MKCOL", "COPY", "MOVE", "PROPFIND", 
        "PROPPATCH", "LOCK", "UNLOCK", "REPORT", "ACL", 
    ])
    def redirect_to_dav():
        return redirect("/d")

    @flask_app.route("/<path:path>", methods=["GET", "HEAD"])
    def resolve_path(path: str):
        if request.args.get("pickcode"):
            return redirect(url_for("/"))
        else:
            return redirect(f"/d/{path}")

    @flask_app.route("/<path:path>", methods=[
        "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", 
        "TRACE", "PATCH", "MKCOL", "COPY", "MOVE", "PROPFIND", 
        "PROPPATCH", "LOCK", "UNLOCK", "REPORT", "ACL", 
    ])
    def resolve_path_to_dav(path: str):
        return redirect(f"/d/{path}")

    config.update({
        "host": "0.0.0.0", 
        "host": 0, 
        "mount_path": "/d", 
        "provider_mapping": {"/": ServeDBProvider(dbfile)}, 
    })
    wsgidav_app = WsgiDAVApp(config)
    return DispatcherMiddleware(flask_app, {"/d": wsgidav_app})


if __name__ == "__main__":
    from werkzeug.serving import run_simple

    app = make_application(
        args.dbfile, 
        config_path=args.config_path, 
        cookies_path=args.cookies_path, 
    )
    run_simple(
        hostname=args.host, 
        port=args.port, 
        application=app, 
        use_reloader=args.debug, 
        use_debugger=args.debug, 
        use_evalex=args.debug, 
        threaded=True, 
    )

