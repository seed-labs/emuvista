# Services

This directory contains reusable SEED Emulator add-on services maintained by EmuVista.

- [CloudDriveService](CloudDriveService/) deploys Nextcloud with PostgreSQL and S3-compatible object storage. It supports co-located or split placement, automatic backend access control, generated credentials, HTTPS integration, and optional persistent state.
- [PaymentBundle](PaymentService/) deploys the Komunitin web wallet and APIs from prebuilt images through SEED's ContainerBundle API, with automatic initialization and optional persistent state.
- [EmailBundle](EmailService/) deploys Mailu SMTP/IMAP, Roundcube Webmail and mailbox administration on SEED networks, with JSON initialization and optional saved state.
