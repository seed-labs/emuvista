"""DNS queries executed in the agent's own network namespace."""

import ipaddress
import re
import subprocess


def lookup(arguments, context):
    name = arguments["name"]
    if name != "." and (
        len(name) > 253
        or not all(
            re.fullmatch(r"[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?", label)
            for label in name.rstrip(".").split(".")
        )
    ):
        raise ValueError("name must be a DNS name, not a URL")
    record_type = arguments.get("record_type", "A")
    if record_type not in (
        "A",
        "AAAA",
        "CNAME",
        "MX",
        "NS",
        "TXT",
        "SOA",
        "PTR",
        "SRV",
        "CAA",
    ):
        raise ValueError("unsupported record type")
    timeout = arguments.get("timeout_seconds", 5)
    command = ["dig", "+time=" + str(timeout), "+tries=1"]
    server = arguments.get("server")
    if server:
        command.append("@" + str(ipaddress.ip_address(server)))
    command.extend([name, record_type])
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout + 3
        )
    except subprocess.TimeoutExpired:
        return {
            "successful": False,
            "command_successful": False,
            "response_status": "timeout",
            "answers": [],
            "records": [],
        }
    match = re.search(r"status: ([A-Z0-9]+),", result.stdout)
    status = (
        match[1] if match else ("timeout" if result.returncode == 9 else "no_response")
    )
    records = []
    in_answer = False
    for line in result.stdout.splitlines():
        if line == ";; ANSWER SECTION:":
            in_answer = True
            continue
        if not line or line.startswith(";"):
            in_answer = False
            continue
        if in_answer:
            fields = line.split(None, 4)
            if len(fields) == 5:
                records.append(
                    {
                        "name": fields[0],
                        "ttl": int(fields[1]),
                        "record_type": fields[3],
                        "value": fields[4],
                    }
                )
    return {
        "successful": result.returncode == 0 and status == "NOERROR",
        "command_successful": result.returncode == 0,
        "response_status": status,
        "exit_code": result.returncode,
        "name": name,
        "record_type": record_type,
        "answers": [r["value"] for r in records if r["record_type"] == record_type],
        "records": records,
    }
