# DNS lookup

`dns.lookup` runs `dig` in the current agent node, without a shell or Docker socket.
Load with `ToolPackage('dns', path, software=['dnsutils'])` and allow `dns.lookup`.

Inputs: DNS `name`, optional `record_type` (default A), optional server IP, and
`timeout_seconds` (default 5, at most 15). Without `server`, the node's configured
resolver is used. Supports A, AAAA, CNAME, MX, NS, TXT, SOA, PTR, SRV and CAA.
For reverse lookup, provide the reverse DNS name with record_type PTR.

Results distinguish `command_successful` from `response_status`: dig can exit
successfully for NXDOMAIN. `successful` requires exit code 0 and NOERROR, but a
NOERROR response may have no answers of the requested type. `answers` contains
values of the requested type; `records` retains the answer section including
CNAMEs and TTLs. No zone or record is created.
