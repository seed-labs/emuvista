# Bundles

ContainerBundle integrations use external images and join rendered SEED networks.
Configure them after `emu.render()` and register them with `compiler.addContainerBundle()`.

- [PaymentBundle](PaymentBundle/): web wallet, payment APIs, initialization and saved state.
- [EmailBundle](EmailBundle/): SMTP/IMAP, webmail and mailbox administration.
- [BankBundle](BankBundle/): banking APIs, customer and staff websites, account and card initialization.

```python
from bundles.PaymentBundle import PaymentBundle
```

SEED service layers remain in [services](../services/).
