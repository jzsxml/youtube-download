import sqlite3

from yt_dlp.cookies import (
    YoutubeDLCookieJar,
    _find_files,
    _get_chromium_based_browser_settings,
    _get_column_names,
    _newest,
    _process_chrome_cookie,
    get_cookie_decryptor,
)
from yt_dlp.cookies import YDLLogger


class L(YDLLogger):
    def debug(self, m): ...
    def info(self, m):
        print("I", m)
    def warning(self, m, *a, **k):
        print("W", m)
    def error(self, m):
        print("E", m)


logger = L()


def extract_ro(browser):
    config = _get_chromium_based_browser_settings(browser)
    search_root = config["browser_dir"]
    db = _newest(list(_find_files(search_root, "Cookies", logger)))
    print("db", db)
    uri = "file:///" + db.replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    cursor = conn.cursor()
    meta_version = int(
        cursor.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()[0]
    )
    decryptor = get_cookie_decryptor(
        config["browser_dir"],
        config["keyring_name"],
        logger,
        meta_version=meta_version,
    )
    cursor.connection.text_factory = bytes
    cols = _get_column_names(cursor, "cookies")
    sc = "is_secure" if "is_secure" in cols else "secure"
    cursor.execute(
        f"SELECT host_key, name, value, encrypted_value, path, expires_utc, {sc} FROM cookies"
    )
    jar = YoutubeDLCookieJar()
    failed = 0
    for line in cursor.fetchall():
        _, cookie = _process_chrome_cookie(decryptor, *line)
        if not cookie:
            failed += 1
            continue
        jar.set_cookie(cookie)
    print("cookies", len(jar), "failed", failed)
    conn.close()
    return jar


for b in ("chrome", "edge"):
    print("===", b)
    try:
        extract_ro(b)
    except Exception as e:
        print("ERR", type(e).__name__, e)