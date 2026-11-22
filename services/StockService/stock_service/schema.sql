CREATE TABLE IF NOT EXISTS stock_accounts (
    id UUID PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL DEFAULT '',
    password_salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    email_verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE stock_accounts ADD COLUMN IF NOT EXISTS display_name TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS email_verifications (
    email TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stock_api_keys (
    id TEXT PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES stock_accounts(id) ON DELETE CASCADE,
    secret_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS stock_positions (
    account_id UUID NOT NULL REFERENCES stock_accounts(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    quantity BIGINT NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    reserved BIGINT NOT NULL DEFAULT 0 CHECK (reserved >= 0 AND reserved <= quantity),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, symbol)
);

CREATE TABLE IF NOT EXISTS stock_allocations (
    allocation_id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES stock_accounts(id),
    symbol TEXT NOT NULL,
    quantity BIGINT NOT NULL CHECK (quantity > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stock_orders (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES stock_accounts(id),
    client_order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    order_type TEXT NOT NULL CHECK (order_type IN ('LIMIT', 'MARKET')),
    quantity BIGINT NOT NULL CHECK (quantity > 0),
    limit_price NUMERIC(20, 8),
    status TEXT NOT NULL,
    filled_quantity BIGINT NOT NULL DEFAULT 0 CHECK (filled_quantity >= 0),
    average_fill_price NUMERIC(20, 8),
    fix_client_order_id TEXT,
    quantreplay_order_id TEXT,
    cancel_client_order_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, client_order_id)
);

ALTER TABLE stock_orders ADD COLUMN IF NOT EXISTS cancel_client_order_id TEXT;
ALTER TABLE stock_orders ADD COLUMN IF NOT EXISTS fix_client_order_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS stock_orders_fix_client_order_id_idx
    ON stock_orders (fix_client_order_id) WHERE fix_client_order_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS stock_fills (
    execution_id TEXT PRIMARY KEY,
    order_id UUID NOT NULL REFERENCES stock_orders(id),
    quantity BIGINT NOT NULL CHECK (quantity > 0),
    price NUMERIC(20, 8) NOT NULL CHECK (price >= 0),
    executed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stock_fix_reports (
    order_id UUID NOT NULL REFERENCES stock_orders(id),
    execution_id TEXT NOT NULL,
    execution_type TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (order_id, execution_id)
);

CREATE TABLE IF NOT EXISTS stock_cash_accounts (
    account_id UUID PRIMARY KEY REFERENCES stock_accounts(id) ON DELETE CASCADE,
    balance NUMERIC(20, 2) NOT NULL DEFAULT 0 CHECK (balance >= 0),
    reserved NUMERIC(20, 2) NOT NULL DEFAULT 0 CHECK (reserved >= 0 AND reserved <= balance),
    currency CHAR(3) NOT NULL DEFAULT 'USD',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stock_cash_ledger (
    entry_id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES stock_accounts(id),
    entry_type TEXT NOT NULL CHECK (entry_type IN (
        'DEPOSIT', 'WITHDRAWAL', 'RESERVE', 'RELEASE', 'BUY_FILL', 'SELL_FILL'
    )),
    balance_delta NUMERIC(20, 2) NOT NULL,
    reserved_delta NUMERIC(20, 2) NOT NULL DEFAULT 0,
    external_reference TEXT,
    order_id UUID REFERENCES stock_orders(id),
    execution_id TEXT REFERENCES stock_fills(execution_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (reserved_delta <= 0 OR entry_type = 'RESERVE')
);

CREATE UNIQUE INDEX IF NOT EXISTS stock_cash_ledger_external_reference_idx
    ON stock_cash_ledger (external_reference) WHERE external_reference IS NOT NULL;

CREATE INDEX IF NOT EXISTS stock_cash_ledger_account_created_idx
    ON stock_cash_ledger (account_id, created_at DESC);

CREATE TABLE IF NOT EXISTS stock_bank_link_attempts (
    state TEXT PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES stock_accounts(id) ON DELETE CASCADE,
    bank_alias TEXT NOT NULL,
    card_id TEXT NOT NULL,
    consent_id UUID NOT NULL,
    verifier TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stock_bank_links (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES stock_accounts(id) ON DELETE CASCADE,
    bank_alias TEXT NOT NULL,
    card_id TEXT NOT NULL,
    card_name TEXT NOT NULL,
    masked_card TEXT NOT NULL,
    currency CHAR(3) NOT NULL,
    encrypted_tokens TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, bank_alias, card_id)
);

CREATE TABLE IF NOT EXISTS stock_cash_deposits (
    id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES stock_accounts(id) ON DELETE CASCADE,
    bank_link_id UUID NOT NULL REFERENCES stock_bank_links(id),
    amount NUMERIC(20, 2) NOT NULL CHECK (amount > 0),
    currency CHAR(3) NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('REQUESTED', 'PENDING', 'COMPLETED', 'DECLINED', 'NEEDS_REVIEW')),
    bank_transaction_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS stock_orders_account_created_idx
    ON stock_orders (account_id, created_at DESC);
