# Services

This directory contains reusable SEED Emulator add-on services maintained by EmuVista.

- [CloudDriveService](CloudDriveService/) deploys Nextcloud with PostgreSQL and S3-compatible object storage. It supports co-located or split placement, automatic backend access control, generated credentials, HTTPS integration, and optional persistent state.
- [PaymentService](PaymentService/) deploys the Komunitin web wallet and APIs from prebuilt images through SEED's ContainerBundle API, with automatic initialization and optional persistent state.
