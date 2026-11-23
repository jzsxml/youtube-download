def is_login_required_message(err: str) -> bool:
    e = err.lower()
    markers = (
        "sign in to confirm your age",
        "confirm your age",
        "please sign in",
        "login required",
        "members only",
        "private video",
        "inappropriate for some users",
        "this video is available",
        "join this channel",
    )
    return any(m in e for m in markers)


def is_format_unavailable(err: str) -> bool:
    e = err.lower()
    return (
        "requested format is not available" in e
        or "no video formats" in e
        or "only images are available" in e
    )


def is_dpapi_error(err: str) -> bool:
    e = err.lower()
    return "dpapi" in e or (
        "decrypt" in e and ("cookie" in e or "failed to decrypt" in e)
    )


def is_cookie_infrastructure_error(err: str) -> bool:
    e = err.lower()
    if "could not copy" in e and "cookie" in e:
        return True
    if "decrypt" in e and ("cookie" in e or "dpapi" in e):
        return True
    if "failed to load cookies" in e:
        return True
    if "does not look like a netscape" in e:
        return True
    if is_dpapi_error(err):
        return True
    return False


def is_video_unavailable_error(err: str) -> bool:
    e = err.lower()
    return (
        "video unavailable" in e
        or "account associated with this video has been terminated" in e
        or "this video has been removed" in e
        or "this video is no longer available" in e
    )


def brief_video_unavailable_message(err: str) -> str:
    if "terminated" in err.lower():
        return "视频不可用（上传者账号已停用），YouTube 无法提供下载。"
    if "removed" in err.lower():
        return "视频已从 YouTube 删除，无法下载。"
    return "视频不可用，无法下载。"


def format_youtube_auth_hint(err: str, auth_mode: str, has_cookies: bool) -> str:
    if not is_login_required_message(err):
        return err
    extra = (
        "\n\n该视频受年龄或登录限制，必须使用已登录的 Cookie。\n"
        "请：1) 点「在应用内登录 YouTube」并在网页中完成登录与年龄确认；\n"
        "2) 点「保存登录状态」；3) 登录态选「本地已同步会话」。"
    )
    if auth_mode == "none" or not has_cookies:
        return err + extra
    return (
        err
        + "\n\n已配置登录但 Cookie 可能无效或过期，请重新「在应用内登录」并保存。"
    )