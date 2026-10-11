"""互刷系统账号名与密码安全工具。

密码哈希使用 Python 标准库 ``hashlib.scrypt``，不引入额外运行依赖。编码中保存
算法版本、参数、随机盐和派生结果，后续可以在登录成功后平滑升级参数。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import unicodedata


SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SALT_BYTES = 16
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
EMAIL_MIN_LENGTH = 5
EMAIL_MAX_LENGTH = 254


def normalize_username(value: str) -> str:
    """返回规范化登录邮箱；互刷账号统一使用邮箱作为唯一登录标识。"""
    email = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    if not EMAIL_MIN_LENGTH <= len(email) <= EMAIL_MAX_LENGTH:
        raise ValueError(f"登录邮箱长度必须为 {EMAIL_MIN_LENGTH}-{EMAIL_MAX_LENGTH} 个字符")
    if email.count("@") != 1:
        raise ValueError("请输入有效的登录邮箱")
    local, domain = email.split("@", 1)
    if not local or len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in local:
        raise ValueError("请输入有效的登录邮箱")
    if not all(char.isalnum() or char in ".!#$%&'*+/=?^_`{|}~-" for char in local):
        raise ValueError("请输入有效的登录邮箱")
    labels = domain.split(".")
    if len(labels) < 2 or any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not all(char.isalnum() or char == "-" for char in label)
        for label in labels
    ):
        raise ValueError("请输入有效的登录邮箱")
    return email


def validate_password(password: str) -> str:
    value = str(password or "")
    if not PASSWORD_MIN_LENGTH <= len(value) <= PASSWORD_MAX_LENGTH:
        raise ValueError(f"密码长度必须为 {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} 个字符")
    return value


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    """使用随机盐生成不可逆 scrypt 哈希。"""
    value = validate_password(password).encode("utf-8")
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.scrypt(
        value,
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return "$".join((
        "scrypt-v1",
        str(SCRYPT_N),
        str(SCRYPT_R),
        str(SCRYPT_P),
        _b64encode(salt),
        _b64encode(digest),
    ))


def verify_password(password: str, encoded: str) -> bool:
    """验证密码；任何损坏或未知编码都安全地返回 ``False``。"""
    try:
        algorithm, raw_n, raw_r, raw_p, raw_salt, raw_digest = str(encoded).split("$", 5)
        if algorithm != "scrypt-v1":
            return False
        n, r, p = int(raw_n), int(raw_r), int(raw_p)
        if n <= 1 or n > SCRYPT_N or r <= 0 or r > SCRYPT_R or p <= 0 or p > SCRYPT_P:
            return False
        candidate = hashlib.scrypt(
            str(password or "").encode("utf-8"),
            salt=_b64decode(raw_salt),
            n=n,
            r=r,
            p=p,
            dklen=SCRYPT_DKLEN,
        )
        return hmac.compare_digest(candidate, _b64decode(raw_digest))
    except (TypeError, ValueError, MemoryError):
        return False
