"""Small structured audit stream shared by HTTP and stdio deployments."""

import json
import logging


class AuditFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = {
            "event": record.getMessage(),
            "time": self.formatTime(record),
        }
        for name in ("agent_id", "world_id", "tool", "invocation_id", "outcome", "resources"):
            if hasattr(record, name):
                fields[name] = getattr(record, name)
        return json.dumps(fields, ensure_ascii=True)


def configure_audit_logging() -> None:
    logger = logging.getLogger("seedemu.auth.audit")
    if not logger.handlers:
        handler = logging.StreamHandler()  # stderr: never corrupt the stdio MCP stream.
        handler.setFormatter(AuditFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
