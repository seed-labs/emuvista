# KnowledgeBundle

A company knowledge base using BookStack, MariaDB and native signed SAML login. Employee
IDs map to external authentication IDs; the directory adapter updates accounts
through the native API. Employees are editors; Company admin maps to the native administrator.

Use the common configuration/network methods and `connectIdentity()`. Build the
image with `docker compose -f docker_images/knowledge/compose.yml build`.
`setSavePath()` preserves the database, uploads and application keys.
See [H98](../../examples/H98_virtual_company/) for company login and deployment.
