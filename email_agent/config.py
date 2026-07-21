"""集中管理所有配置项，从 config.txt 读取。"""
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))


def _load_config():
    path = os.path.join(_PROJECT_ROOT, "config.txt")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"配置文件不存在: {path}")

    cfg = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                cfg[key.strip()] = val.strip()
    return cfg


_cfg = _load_config()

IMAP_SERVER = _cfg.get("imap_server", "imap.exmail.qq.com")
IMAP_PORT   = int(_cfg.get("imap_port", "993"))
EMAIL       = _cfg.get("email", "")
PASSWORD    = _cfg.get("password", "")

SMTP_SERVER = _cfg.get("smtp_server", "smtp.exmail.qq.com")
SMTP_PORT   = int(_cfg.get("smtp_port", "465"))
SEND_TO     = _cfg.get("send_to", "")  # 日报发送目标邮箱，为空则发送给 EMAIL 自己

SAVE_ATTACHMENTS  = True
OUTPUT_DIR_NAME    = "output"
OUTPUT_FORMAT      = _cfg.get("output_format", "both")  # "html" | "markdown" | "both"
MAX_SAFE_NAME_LENGTH = 120
