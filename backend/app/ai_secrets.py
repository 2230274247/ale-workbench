"""Write-only provider secrets encrypted with a machine-local Fernet master key."""
import os
import stat
import subprocess
from cryptography.fernet import Fernet, InvalidToken
from .config import BACKEND

KEY_PATH = BACKEND / '.ai-master-key'


def _protect(path):
    if os.name == 'nt':
        # Remove inherited access and grant only this Windows account.
        identity = subprocess.run(['whoami'], capture_output=True, text=True, check=True).stdout.strip()
        subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', identity + ':F'],
                       capture_output=True, check=True)
    else:
        os.chmod(path, 0o600)


def _fernet(create=False):
    if create and not KEY_PATH.exists():
        try:
            fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            try:
                _protect(KEY_PATH)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(Fernet.generate_key())
                    stream.flush()
                    os.fsync(stream.fileno())
                _protect(KEY_PATH)
            except Exception:
                KEY_PATH.unlink(missing_ok=True)
                raise RuntimeError('AI secret storage unavailable') from None
    try:
        if KEY_PATH.is_symlink():
            raise ValueError()
        if os.name != 'nt' and stat.S_IMODE(KEY_PATH.stat().st_mode) & 0o077:
            raise ValueError()
        return Fernet(KEY_PATH.read_bytes())
    except (OSError, ValueError):
        raise RuntimeError('AI secret storage unavailable') from None


def encrypt_key(value):
    return _fernet(create=True).encrypt(value.encode()).decode('ascii')


def decrypt_key(value):
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError, UnicodeError):
        raise RuntimeError('AI secret storage unavailable') from None
