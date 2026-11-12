"""Move the PayWay credentials from secrets/credential_info.txt into .env and secrets/*.pem
without ever printing a value.

    python3 scripts/payway_setup.py inspect
        The file's shape only: line number, a label when it is plainly a label, and for each
        value its kind and length. Values are never shown.

    python3 scripts/payway_setup.py apply --base-url 3:2 --merchant-id 1:3 --api-key 5 --rsa-public 10-13 [--rsa-private 15-30]
        Line numbers, ranges, or LINE:WORD from `inspect`. Writes the PAYWAY_* lines in .env (a copy of the
        old file goes to .env.bak) and secrets/payway_rsa_public.pem (+ private), mode 600,
        adding the BEGIN/END lines when the key has none. Prints only what was set.
"""

import argparse
import base64
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "secrets" / "credential_info.txt"
ENV = ROOT / ".env"
PEM_PUBLIC = ROOT / "secrets" / "payway_rsa_public.pem"
PEM_PRIVATE = ROOT / "secrets" / "payway_rsa_private.pem"
LABEL = re.compile(r"^\s*([A-Za-z][A-Za-z ()/_.-]{0,38})\s*[:=]\s*(.*)$")  # "Merchant ID: …" – words only
SAFE_WORDS = {"merchant", "id", "api", "key", "public", "private", "rsa", "url", "base", "secret", "link", "password",
              "username", "user", "name", "sandbox", "production", "prod", "test", "endpoint", "hash", "profile",
              "payway", "aba", "app", "client", "token", "account", "email", "phone", "environment", "env", "host",
              "domain", "callback", "return", "webhook", "the", "for", "of", "and", "or", "(", ")"}


def safe_label(label: str) -> str:
    """The label only when it is made of ordinary label words; anything else could be a key fragment."""
    words = [w for w in re.split(r"[\s_./()-]+", label.lower()) if w]
    return label if words and all(w in SAFE_WORDS for w in words) else "(label hidden)"


ENV_KEYS = {
    "base_url": "PAYWAY_BASE_URL",
    "merchant_id": "PAYWAY_MERCHANT_ID",
    "api_key": "PAYWAY_API_KEY",
}


def kind_of(value: str) -> str:
    v = value.strip()
    if re.fullmatch(r"https?://\S+", v):
        return "url"
    if not v:
        return "empty"
    if v.startswith("-----BEGIN"):
        return "pem header"
    if v.startswith("-----END"):
        return "pem footer"
    if re.fullmatch(r"https?://\S+", v):
        return "url"
    if re.fullmatch(r"\d+", v):
        return "number"
    if re.fullmatch(r"[0-9a-fA-F]+", v):
        return "hex"
    if re.fullmatch(r"[A-Za-z0-9+/=]+", v):
        return "base64-like"
    if re.fullmatch(r"[A-Za-z0-9._@-]+", v):
        return "word"
    return "text"


def read_lines() -> list[str]:
    if not SOURCE.exists():
        sys.exit(f"{SOURCE.relative_to(ROOT)} not found")
    return SOURCE.read_text(encoding="utf-8", errors="replace").splitlines()


def tokens(line: str) -> list[str]:
    return [t for t in re.split(r"(\s+|:|=)", line) if t.strip()]


def describe_tokens(line: str) -> str:
    """Each word of the line: shown when it is an ordinary label word or separator, else kind + length."""
    out = []
    for i, t in enumerate(tokens(line), 1):
        plain = t.strip()
        if plain in (":", "=", "-", "–") or plain.lower().strip("()") in SAFE_WORDS:
            out.append(f"{i}:{plain!r}")
        else:
            out.append(f"{i}:<{kind_of(plain)} {len(plain)}>")
    return " ".join(out)


def inspect() -> None:
    for n, line in enumerate(read_lines(), 1):
        if kind_of(line) == "text":
            print(f"line {n:3}: words {describe_tokens(line)}")
            continue
        m = LABEL.match(line)
        label, value = (m.group(1).strip(), m.group(2)) if m and kind_of(m.group(2)) != "empty" else ("", line)
        if m and kind_of(m.group(2)) == "empty":
            print(f"line {n:3}: label {safe_label(m.group(1).strip())!r} (value on the next lines?)")
            continue
        shown = f"label {safe_label(label)!r}, " if label else ""
        print(f"line {n:3}: {shown}value hidden: {kind_of(value)}, {len(value.strip())} chars")


def pick(lines: list[str], spec: str) -> list[str]:
    if ":" in spec:  # one word of one line: "3:4" = line 3, word 4 (numbers from inspect)
        n, w = (int(x) for x in spec.split(":", 1))
        words = tokens(lines[n - 1]) if 1 <= n <= len(lines) else []
        if not 1 <= w <= len(words):
            sys.exit(f"word {spec} is not in the file")
        return [words[w - 1].strip()]
    a, _, b = spec.partition("-")
    first, last = int(a), int(b or a)
    if not 1 <= first <= last <= len(lines):
        sys.exit(f"line range {spec} is outside the file")
    out = []
    for line in lines[first - 1 : last]:
        if kind_of(line) == "url":  # "https://…" is a value, not "label: value"
            out.append(line.strip())
            continue
        m = LABEL.match(line)
        out.append((m.group(2) if m and kind_of(m.group(2)) != "empty" else line).strip())
    return [x for x in out if x]


def as_pem(parts: list[str], private: bool) -> str:
    body = "".join(p for p in parts if not p.startswith("-----"))
    try:
        base64.b64decode(body, validate=True)
    except ValueError:
        sys.exit("the key lines are not base64: check the line numbers")
    name = "PRIVATE KEY" if private else "PUBLIC KEY"
    if any(p.startswith("-----BEGIN") for p in parts):
        name = next(p for p in parts if p.startswith("-----BEGIN"))[11:].strip("- ")
    wrapped = "\n".join(body[i : i + 64] for i in range(0, len(body), 64))
    return f"-----BEGIN {name}-----\n{wrapped}\n-----END {name}-----\n"


def env_value(v: str) -> str:
    return '"' + v.replace("$", "$$").replace('"', '\\"') + '"'  # compose: $ is written $$


def write_env(values: dict[str, str]) -> None:
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    if ENV.exists():
        shutil.copy2(ENV, ROOT / ".env.bak")
    for key, value in values.items():
        new = f"{key}={env_value(value)}"
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = new
                break
        else:
            lines.append(new)
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_pem(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    try:  # prove the key loads; its size is not secret
        from cryptography.hazmat.primitives import serialization

        data = text.encode()
        key = (serialization.load_pem_private_key(data, password=None) if "PRIVATE" in text
               else serialization.load_pem_public_key(data))  # fmt: skip
        print(f"  loads: RSA {key.key_size} bit")
    except ImportError:
        print("  (cryptography not installed here: run with .venv/bin/python to check the key loads)")
    except ValueError:
        sys.exit(f"  {path.name} does not load as a key: check the line numbers")


def env_get(key: str) -> str | None:
    if not ENV.exists():
        return None
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            v = line.split("=", 1)[1].strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            return v.replace("$$", "$")
    return None


def compare(args: argparse.Namespace) -> None:
    """Says whether each .env value equals the one in the file: "matches" / "differs" / "not in .env"."""
    from urllib.parse import urlsplit

    lines = read_lines()
    for arg, key in ENV_KEYS.items():
        spec = getattr(args, arg)
        if not spec:
            continue
        mine, theirs = pick(lines, spec)[0], env_get(key)
        if key == "PAYWAY_BASE_URL" and theirs:  # the file may give a full endpoint: compare scheme + host
            mine, theirs = urlsplit(mine)._replace(path="", query="").geturl(), urlsplit(theirs)._replace(path="", query="").geturl()
        state = "not in .env" if theirs is None else "matches" if mine == theirs else "differs"
        print(f"{key}: {state}")


def apply(args: argparse.Namespace) -> None:
    lines = read_lines()
    values = {}
    for arg, key in ENV_KEYS.items():
        spec = getattr(args, arg)
        if spec:
            got = pick(lines, spec)
            if len(got) != 1:
                sys.exit(f"--{arg.replace('_', '-')}: expected one value on line {spec}")
            values[key] = got[0]
    if args.rsa_public:
        write_pem(PEM_PUBLIC, as_pem(pick(lines, args.rsa_public), private=False))
        values["PAYWAY_RSA_PUBLIC_KEY_SOURCE"] = "./secrets/payway_rsa_public.pem"  # compose secret (host path)
        print(f"written {PEM_PUBLIC.relative_to(ROOT)} (mode 600)")
    if args.rsa_private:
        write_pem(PEM_PRIVATE, as_pem(pick(lines, args.rsa_private), private=True))
        values["PAYWAY_RSA_PRIVATE_KEY_SOURCE"] = "./secrets/payway_rsa_private.pem"
        print(f"written {PEM_PRIVATE.relative_to(ROOT)} (mode 600)")
    if values:
        write_env(values)
        for key in values:
            print(f"set {key} in .env")
        print("old .env kept as .env.bak")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect")
    for command in ("apply", "compare"):
        ap = sub.add_parser(command)
        for name in ("base-url", "merchant-id", "api-key", "rsa-public", "rsa-private"):
            ap.add_argument(f"--{name}", metavar="LINES")
    args = parser.parse_args()
    {"inspect": lambda: inspect(), "apply": lambda: apply(args), "compare": lambda: compare(args)}[args.command]()


if __name__ == "__main__":
    main()
