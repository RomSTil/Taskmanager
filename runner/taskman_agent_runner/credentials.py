"""Store the runner token in the current Windows user's Credential Manager."""

import ctypes
import os
from ctypes import wintypes


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", ctypes.c_byte * 8),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _target(runner_id: str) -> str:
    return f"TaskmanAgentRunner:{runner_id}"


def save_runner_token(runner_id: str, token: str) -> None:
    if os.name != "nt":
        raise RuntimeError("Taskman Agent Runner stores tokens in Windows Credential Manager only")
    encoded = token.encode("utf-16-le")
    blob = (ctypes.c_byte * len(encoded)).from_buffer_copy(encoded)
    credential = _Credential(
        Type=CRED_TYPE_GENERIC,
        TargetName=_target(runner_id),
        CredentialBlobSize=len(encoded),
        CredentialBlob=ctypes.cast(blob, ctypes.POINTER(ctypes.c_byte)),
        Persist=CRED_PERSIST_LOCAL_MACHINE,
        UserName="Taskman Agent Runner",
    )
    written = ctypes.windll.advapi32.CredWriteW(ctypes.byref(credential), 0)
    if not written:
        raise ctypes.WinError(ctypes.get_last_error())


def load_runner_token(runner_id: str) -> str:
    if os.name != "nt":
        raise RuntimeError("Taskman Agent Runner requires Windows Credential Manager")
    pointer = ctypes.POINTER(_Credential)()
    found = ctypes.windll.advapi32.CredReadW(
        _target(runner_id), CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)
    )
    if not found:
        raise RuntimeError("Runner token is missing; pair this runner again")
    try:
        size = int(pointer.contents.CredentialBlobSize)
        raw = ctypes.string_at(pointer.contents.CredentialBlob, size)
        return raw.decode("utf-16-le")
    finally:
        ctypes.windll.advapi32.CredFree(pointer)
