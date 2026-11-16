# Simulated domain purchase

`domain_purchase.purchase` performs a one-year FOSSBilling domain checkout,
submits its signed FakePayment confirmation once, and verifies a paid invoice
and active registrar order. It follows the existing H12 customer API workflow.
It does not buy DNS hosting, set nameservers, add records, or prove Registry/DNS
propagation. Only configured second-level suffixes are accepted (.com/.net in E15).

Arguments: `domain` and `max_amount_minor` (USD cents in E15). The payment limit
is checked against the signed form amount before confirmation. Checkout happens
first, so an over-limit request leaves an unpaid order/invoice. No real payment
gateway is selected: the only supported gateway is FakePayment.

`domain_purchase.status` takes `domain` and rechecks the local order with the
registrar. It never submits a payment. `successful` means both invoice=paid and
order=active; inspect `stage`, `order_status`, `invoice_status`, and
`outcome_unknown` for incomplete operations. No invoice hash or signature is
returned to the model.

Connection and account are bound by the experiment:

```python
agents.addToolPackage(ToolPackage('domain_purchase', ROOT / 'bundles/DomainRegistrarBundle/tools'))
agent.setService('domain_purchase', {
    'registrar_url': 'http://10.150.0.71:8080',
    'payment_url': 'http://10.160.0.71:8080',
    'email': 'alice@example.com', 'password': 'seedalice',
    'currency': 'USD', 'tlds': ['com', 'net'],
    'state_dir': '/home/emuvista-agent/domain-purchases',
})
```

Use the registrar origin that matches the configured FakePayment callback origin.
The tool rejects redirects, disables environment proxy lookup, and keeps payment
requests separate from registrar cookies. It uses a fresh customer session per
call and never accepts credentials, API endpoints or payment URLs from the model.

E15 gives each agent its imported customer account and a separate persistent
journal volume. Keep that volume: the journal and file lock prevent repeat
checkouts for the same account/domain, including after a process restart. It is
not a server-wide idempotency guarantee. An existing purchase outside this journal
is not detected by local deduplication. If checkout loses its response before its
order ID is saved, use the customer portal to reconcile; the tool will not retry.
Incomplete orders, including over-limit ones, require portal intervention instead
of clearing the journal and blindly submitting another purchase.

## Nameservers and DNS Hosting

- `domain_purchase.set_nameservers`: pass the domain registration `order_id` and
  two to four distinct `nameservers`. FOSSBilling enforces account ownership and
  active domain status. This replaces the NS list; it does not create Registry
  host/glue objects. `successful` means the registrar accepted the update, not
  that DNS propagation was verified. Inspect the portal before retrying an
  uncertain result.
- `domain_purchase.hosting_purchase`: pass `domain` and `max_amount_minor` to
  order DNS Hosting (not website hosting). The current experiment product is
  free; a zero limit permits free hosting only. Paid products use the same
  signed FakePayment checks as domain registration. Exactly one DNS product
  must be offered. An over-limit checkout leaves an unpaid order.
- `domain_purchase.hosting_status`: pass `domain` to recheck that hosting order.
  Success requires an active order and a paid invoice, or no invoice for a free
  checkout. It does not verify zone contents or end-to-end DNS resolution.

Hosting journals use separate `.hosting.json` files, so domain registration and
hosting orders cannot be mistaken for one another. Preserve both journals. Do
not run purchase tools concurrently for the same customer: they share the
registrar's shopping cart. Orders created outside these journals are not deduplicated.

Add tool names to the experiment's
`allowTools` list to expose them to an agent; existing E15 tasks and permissions
are unchanged. No account creation, renewals, transfers or cancellations are added.

## DNS records

`dns_list`, `dns_add`, `dns_update`, and `dns_delete` use the `domain_purchase.`
prefix and require `domain` (zone name) and `order_id` (active DNS Hosting order,
not registration order). The customer API enforces ownership; tools also check
service type and domain before writing. Provider configuration is never returned.

For `www.seed.com`, use `domain="seed.com"`, `record_name="www"`,
`record_type="A"`, `record_value="192.0.2.123"`, `record_ttl=60` with `dns_add`
after obtaining the hosting order ID and listing existing records.
`dns_list` returns record IDs; `dns_update` takes `record_id`, `record_value`,
`record_ttl`, and optional `record_priority` for MX. It preserves name and type.
`dns_delete` takes `record_id` and removes only that record.

Writes are submitted once. On `outcome_unknown=true`, query records before
retrying. `successful=true` means API acceptance; `records_readback` reports
whether a subsequent service read succeeded. Neither proves DNS propagation.
The interfaces follow FOSSBilling 0.8.7 `client/order/service` and the pinned
fossbilling-dns v1.2.7 `client/servicedns/{add,update,del}` APIs.
H13 discovers all tools during regeneration; other experiments must explicitly
allow the new tool names if they use an allow-list.
