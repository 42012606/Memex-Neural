import urllib.parse
from pathlib import PurePosixPath
from src.core.config import settings


def get_file_public_url(relative_path: str) -> str:
    """
    构造文件的公网访问 URL，确保文件名安全编码（支持中文）。
    """
    base_url = settings.FILE_SERVICE_BASE_URL.rstrip("/")
    if not relative_path:
        return f"{base_url}/files"

    # 规范化为 POSIX 路径，移除多余前导斜杠
    rel = str(PurePosixPath(str(relative_path))).lstrip("/")
    rel_path = PurePosixPath(rel)

    # 仅对文件名部分进行 URL 编码，目录保持原样
    encoded_name = urllib.parse.quote(rel_path.name)
    if rel_path.parent and str(rel_path.parent) != ".":
        encoded_path = f"{rel_path.parent.as_posix()}/{encoded_name}"
    else:
        encoded_path = encoded_name

    return f"{base_url}/files/{encoded_path}"

