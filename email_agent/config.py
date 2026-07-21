"""集中管理所有配置项，从 config.txt 读取。

模块级常量通过 ``__getattr__`` 惰性加载，仅在首次访问时读取配置文件，
避免 ``import`` 阶段因 config.txt 缺失而崩溃（如 ``--help`` 等纯 CLI 操作）。
"""
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))

_cfg = None


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


def _get_cfg():
    global _cfg
    if _cfg is None:
        _cfg = _load_config()
    return _cfg


def __getattr__(name):
    if name == "IMAP_SERVER":
        return _get_cfg().get("imap_server", "imap.exmail.qq.com")
    if name == "IMAP_PORT":
        return int(_get_cfg().get("imap_port", "993"))
    if name == "EMAIL":
        return _get_cfg().get("email", "")
    if name == "PASSWORD":
        return _get_cfg().get("password", "")
    if name == "SMTP_SERVER":
        return _get_cfg().get("smtp_server", "smtp.exmail.qq.com")
    if name == "SMTP_PORT":
        return int(_get_cfg().get("smtp_port", "465"))
    if name == "SEND_TO":
        return _get_cfg().get("send_to", "")
    if name == "SAVE_ATTACHMENTS":
        return True
    if name == "OUTPUT_DIR_NAME":
        return "output"
    if name == "OUTPUT_FORMAT":
        return _get_cfg().get("output_format", "both")
    if name == "MAX_SAFE_NAME_LENGTH":
        return 120
    if name == "MODEL_NAME":
        return _get_cfg().get("model_name", "deepseek-v4-flash")
    raise AttributeError(f"module 'email_agent.config' has no attribute '{name}'")
